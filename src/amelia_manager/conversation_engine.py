from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import re
from typing import Protocol
from zoneinfo import ZoneInfo

from amelia_manager.client_order_summary import format_client_order_summary
from amelia_manager.company_profile import CompanyProfile, load_company_profile
from amelia_manager.deterministic_replies import deterministic_order_reply
from amelia_manager.delivery_questions import is_city_delivery_price_question, is_delivery_price_question
from amelia_manager.emoji_variation import vary_reply_emoji
from amelia_manager.humanizer import split_into_telegram_messages, suppress_emojis
from amelia_manager.intent import is_greeting_only
from amelia_manager.llm_client import LLMError
from amelia_manager.model_decision import ModelDecision, parse_model_decision
from amelia_manager.order_card import OrderCard, format_budget_display, merge_order_patch
from amelia_manager.order_policy import NextStep, get_next_step
from amelia_manager.order_state import extract_order_state, is_deferred_date_choice, is_deferred_fulfillment_choice, is_deferred_time_choice
from amelia_manager.prompts import build_manager_prompt
from amelia_manager.risk import RiskCategory, RiskLevel, assess_risk
from amelia_manager.safety import SafetyResult, check_reply_safety, safety_retry_guidance_for_reasons
from amelia_manager.stock import BudgetOption, BudgetOptions, is_budget_unknown_answer
from amelia_manager.structured_generation import generate_with_optional_schema


class LLM(Protocol):
    async def generate(self, prompt: str, **kwargs) -> str: ...


@dataclass(frozen=True)
class ConversationAction:
    kind: str
    messages: list[str]
    risk_level: RiskLevel
    safety_reasons: list[str] = field(default_factory=list)
    order_patch: dict[str, object] = field(default_factory=dict)
    intent: str | None = None
    next_step: str | None = None
    confidence: float | None = None
    order_scope: str = "continue"
    risk_category: RiskCategory | None = None
    safety_triggered_reasons: list[str] = field(default_factory=list)
    safety_retry_succeeded: bool | None = None

    @property
    def parse_retry_succeeded(self) -> bool | None:
        if "parse_failed" not in self.safety_reasons:
            return None
        return self.safety_retry_succeeded


class ConversationEngine:
    def __init__(self, llm: LLM, *, company_profile: CompanyProfile | None = None) -> None:
        self.llm = llm
        self.company_profile = company_profile or load_company_profile("amelia_flowers")

    async def handle_messages(
        self,
        *,
        client_summary: str,
        recent_messages: list[str],
        stage: str,
        stock_context: str | None = None,
        order_card: OrderCard | None = None,
        budget_options: BudgetOptions | list[BudgetOption] | None = None,
    ) -> ConversationAction:
        last_client_text = _last_client_text(recent_messages)
        risk = assess_risk(last_client_text, company_profile=self.company_profile)
        risk_level = risk.level
        if is_greeting_only(last_client_text):
            return ConversationAction(
                kind="send",
                messages=["Здравствуйте 🙂 Чем могу помочь?"],
                risk_level=risk_level,
            )

        if _is_photo_only(last_client_text):
            return ConversationAction(
                kind="send",
                messages=["Вижу фото, могу ориентироваться на этот стиль. Подскажите, пожалуйста, бюджет?"],
                risk_level=risk_level,
            )

        if _is_media_only(last_client_text):
            return ConversationAction(
                kind="send",
                messages=["Вижу вложение. Напишите, пожалуйста, что именно нужно по заказу, и я помогу сориентироваться."],
                risk_level=risk_level,
            )

        if risk_level == RiskLevel.HIGH:
            return ConversationAction(
                kind="human_takeover",
                messages=[
                    "Понимаю вас. Передам вопрос ответственному менеджеру, чтобы посмотрели детали и вернулись с решением."
                ],
                risk_level=risk_level,
                risk_category=risk.category,
            )

        catalog_price_reply = None
        if risk.category != RiskCategory.OUT_OF_AREA_DELIVERY:
            catalog_price_reply = _catalog_price_reply_for_question(
                last_client_text,
                stock_context,
                company_profile=self.company_profile,
            )
        if catalog_price_reply:
            return ConversationAction(kind="send", messages=[catalog_price_reply], risk_level=risk_level)

        cautious_reply = _cautious_reply_for_medium_risk(
            risk.category,
            stock_context=stock_context,
            latest_text=last_client_text,
            company_profile=self.company_profile,
        )
        if cautious_reply:
            order_patch = _sensitive_occasion_patch(risk.category)
            return ConversationAction(
                kind="send",
                messages=[cautious_reply],
                risk_level=risk_level,
                order_patch=order_patch,
                risk_category=risk.category,
            )

        if order_card and order_card.client_summary_sent and _is_thanks_only(last_client_text):
            return ConversationAction(
                kind="send",
                messages=["Спасибо, ждём вас 🌸"],
                risk_level=risk_level,
            )

        if order_card and order_card.is_ready_for_admin_request():
            if order_card.client_summary_sent:
                return ConversationAction(
                    kind="human_review",
                    messages=["Передам менеджеру, чтобы вам ответили по заказу корректно."],
                    risk_level=risk_level,
                    safety_reasons=["ready_order_already_summarized"],
                    risk_category=risk.category,
                )
            return ConversationAction(
                kind="send",
                messages=[format_client_order_summary(order_card, company_profile=self.company_profile)],
                risk_level=risk_level,
            )

        if order_card and order_card.custom_fields.get("upsell_offered") is True and _is_upsell_decline(last_client_text):
            next_step = NextStep("ask_sender_contacts", "Попроси имя и телефон отправителя для связи по заказу.")
            reply = deterministic_order_reply(
                next_step,
                order_card,
                recent_messages=recent_messages,
                stock_context=stock_context or "",
                company_profile=self.company_profile,
                budget_options=budget_options,
            )
            return ConversationAction(
                kind="send",
                messages=[reply or "Подскажите ваше имя и номер телефона для связи по заказу."],
                risk_level=risk_level,
                next_step=next_step.code,
                order_patch={"custom_fields": {"upsell_declined": True}},
            )

        order_state = order_card or extract_order_state(recent_messages)
        next_step = get_next_step(order_state, company_profile=self.company_profile)
        sensitive_occasion = _has_sensitive_occasion_context(
            recent_messages,
            order_card=order_card,
            company_profile=self.company_profile,
        )
        if next_step.code == "ask_fulfillment_type" and is_deferred_fulfillment_choice(last_client_text):
            pickup_address = self.company_profile.pickup_address or "адреса самовывоза"
            reply = self.company_profile.default_fulfillment_choice_reply_template.format(pickup_address=pickup_address)
            return ConversationAction(
                kind="send",
                messages=_finalize_messages(reply, sensitive_occasion=sensitive_occasion, company_profile=self.company_profile),
                risk_level=risk_level,
                next_step=next_step.code,
            )
        if next_step.code == "ask_date" and is_deferred_date_choice(last_client_text):
            reply = _default_date_choice_reply(self.company_profile)
            return ConversationAction(
                kind="send",
                messages=_finalize_messages(reply, sensitive_occasion=sensitive_occasion, company_profile=self.company_profile),
                risk_level=risk_level,
                next_step=next_step.code,
            )
        if next_step.code in {"ask_pickup_time", "ask_delivery_time"} and is_deferred_time_choice(last_client_text):
            reply = self.company_profile.default_time_choice_reply_template.format(time=self.company_profile.default_time_value)
            return ConversationAction(
                kind="send",
                messages=_finalize_messages(reply, sensitive_occasion=sensitive_occasion, company_profile=self.company_profile),
                risk_level=risk_level,
                next_step=next_step.code,
            )
        if next_step.code == "ask_budget" and is_budget_unknown_answer(last_client_text):
            reply = deterministic_order_reply(
                next_step,
                order_card if isinstance(order_card, OrderCard) else None,
                recent_messages=recent_messages,
                stock_context=stock_context or "",
                company_profile=self.company_profile,
                budget_options=budget_options,
            )
            if reply:
                return ConversationAction(
                    kind="send",
                    messages=_finalize_messages(reply, sensitive_occasion=sensitive_occasion, company_profile=self.company_profile),
                    risk_level=risk_level,
                    next_step=next_step.code,
                )

        if next_step.code == "ask_pickup_time_within_shop_hours":
            reply = deterministic_order_reply(
                next_step,
                order_card if isinstance(order_card, OrderCard) else None,
                recent_messages=recent_messages,
                stock_context=stock_context or "",
                company_profile=self.company_profile,
                budget_options=budget_options,
            )
            if reply:
                return ConversationAction(
                    kind="send",
                    messages=[reply],
                    risk_level=risk_level,
                    next_step=next_step.code,
                )
        if next_step.code == "ask_upsell" and isinstance(order_card, OrderCard):
            reply = deterministic_order_reply(
                next_step,
                order_card if isinstance(order_card, OrderCard) else None,
                recent_messages=recent_messages,
                stock_context=stock_context or "",
                company_profile=self.company_profile,
                budget_options=budget_options,
            )
            if reply:
                return ConversationAction(
                    kind="send",
                    messages=[reply],
                    risk_level=risk_level,
                    next_step=next_step.code,
                    order_patch=_action_patch_for_next_step(next_step.code),
                )

        prompt = build_manager_prompt(
            client_summary=client_summary,
            recent_messages=recent_messages,
            stage=stage,
            risk_level=risk_level,
            next_step_instruction=next_step.instruction,
            stock_context=stock_context,
            company_profile=self.company_profile,
            order_card_context=_format_order_card_context(order_card, sensitive_occasion=sensitive_occasion, company_profile=self.company_profile) if order_card else None,
            sensitive_occasion=sensitive_occasion,
        )
        try:
            reply = await generate_with_optional_schema(
                self.llm,
                prompt,
                response_schema=ModelDecision.model_json_schema(),
            )
        except LLMError:
            fallback = deterministic_order_reply(
                next_step,
                order_card if isinstance(order_card, OrderCard) else None,
                recent_messages=recent_messages,
                stock_context=stock_context or "",
                company_profile=self.company_profile,
                budget_options=budget_options,
            )
            if fallback:
                return ConversationAction(
                    kind="send",
                    messages=[fallback],
                    risk_level=risk_level,
                    safety_reasons=["llm_error_fallback"],
                    next_step=next_step.code,
                    order_patch=_action_patch_for_next_step(next_step.code),
                )
            return ConversationAction(
                kind="human_review",
                messages=["Сейчас передам менеджеру, чтобы вам ответили по заказу корректно."],
                risk_level=risk_level,
                safety_reasons=["llm_error"],
            )
        decision = parse_model_decision(reply)
        action_metadata: dict[str, object] = {}
        if decision is None and _looks_like_model_decision_payload(reply):
            retry_result = await self._retry_or_fallback_after_parse_failure(
                prompt=prompt,
                next_step=next_step,
                order_card=order_card,
                recent_messages=recent_messages,
                stock_context=stock_context,
                risk_level=risk_level,
                sensitive_occasion=sensitive_occasion,
            )
            if retry_result is not None:
                return retry_result
            reply = deterministic_order_reply(
                next_step,
                order_card if isinstance(order_card, OrderCard) else None,
                recent_messages=recent_messages,
                stock_context=stock_context or "",
                company_profile=self.company_profile,
                budget_options=budget_options,
            ) or "Передам менеджеру, чтобы вам ответили корректно."
            return ConversationAction(
                kind="send",
                messages=_finalize_messages(reply, sensitive_occasion=sensitive_occasion, company_profile=self.company_profile),
                risk_level=risk_level,
                safety_reasons=["parse_failed"],
                safety_retry_succeeded=False,
            )

        if decision is None:
            safety = check_reply_safety(reply, stock_context=stock_context, company_profile=self.company_profile, order_card=order_card)
        if decision is not None:
            reply = decision.reply
            action_metadata = {
                "order_patch": dict(decision.case_patch),
                "intent": decision.intent,
                "next_step": decision.next_step,
                "confidence": decision.confidence,
                "order_scope": decision.order_scope,
            }
            if decision.next_step == "ask_upsell":
                action_metadata["order_patch"] = _merge_action_patch(
                    action_metadata["order_patch"],
                    _action_patch_for_next_step(decision.next_step),
                )
            reply = _ensure_pickup_address_for_pickup_time(
                reply,
                decision.next_step,
                merge_order_patch(order_card or OrderCard(), dict(decision.case_patch)),
                self.company_profile,
            )
            if decision.confidence is not None and decision.confidence < 0.5:
                return ConversationAction(
                    kind="human_review",
                    messages=["Передам менеджеру, чтобы точно проверить и ответить вам корректно."],
                    risk_level=risk_level,
                    safety_reasons=["low_model_confidence"],
                    intent=decision.intent,
                    next_step=decision.next_step,
                    confidence=decision.confidence,
                    risk_category=risk.category,
                )
            if decision.needs_human:
                return ConversationAction(
                    kind="human_review",
                    messages=_finalize_messages(reply, sensitive_occasion=sensitive_occasion, company_profile=self.company_profile),
                    risk_level=risk_level,
                    safety_reasons=["model_decision_needs_human"],
                    risk_category=risk.category,
                    **action_metadata,
                )
            safety = check_reply_safety(reply, stock_context=stock_context, company_profile=self.company_profile, order_card=order_card)
        sensitive_tone_reasons = _sensitive_tone_violations(reply, self.company_profile) if sensitive_occasion else []
        if sensitive_tone_reasons:
            safety = SafetyResult(is_safe=False, reasons=[*safety.reasons, *sensitive_tone_reasons])
        if not safety.is_safe:
            triggered_reasons = list(safety.reasons)
            try:
                guidance = safety_retry_guidance_for_reasons(safety.reasons)
                rewrite_prompt = (
                    prompt
                    + "\n\nТвой прошлый ответ нарушил правило безопасности: "
                    + ", ".join(safety.reasons)
                    + ("\nРазрешённая безопасная альтернатива:\n" + guidance if guidance else "")
                    + "\nПерепиши ответ коротко, естественно и без нарушения. Не объясняй правила."
                )
                retry_reply = await generate_with_optional_schema(
                    self.llm,
                    rewrite_prompt,
                    response_schema=ModelDecision.model_json_schema(),
                )
                retry_decision = parse_model_decision(retry_reply)
                if retry_decision is None and _looks_like_model_decision_payload(retry_reply):
                    fallback = deterministic_order_reply(
                        next_step,
                        order_card if isinstance(order_card, OrderCard) else None,
                        recent_messages=recent_messages,
                        stock_context=stock_context,
                        company_profile=self.company_profile,
                    )
                    if fallback:
                        return ConversationAction(
                            kind="send",
                            messages=_finalize_messages(fallback, sensitive_occasion=sensitive_occasion, company_profile=self.company_profile),
                            risk_level=risk_level,
                            safety_reasons=["parse_failed"],
                            safety_triggered_reasons=safety.reasons,
                            safety_retry_succeeded=False,
                        )
                    return ConversationAction(
                        kind="human_review",
                        messages=["Передам менеджеру, чтобы точно проверить и ответить вам корректно."],
                        risk_level=risk_level,
                        safety_reasons=["parse_failed"],
                        risk_category=risk.category,
                        safety_triggered_reasons=safety.reasons,
                        safety_retry_succeeded=False,
                    )
                if retry_decision is None:
                    pass
                else:
                    retry_reply = retry_decision.reply
                    if retry_decision.needs_human:
                        return ConversationAction(
                            kind="human_review",
                            messages=_finalize_messages(retry_reply, sensitive_occasion=sensitive_occasion, company_profile=self.company_profile),
                            risk_level=risk_level,
                            safety_reasons=["model_decision_needs_human"],
                            risk_category=risk.category,
                        )
                retry_safety = check_reply_safety(
                    retry_reply,
                    stock_context=stock_context,
                    company_profile=self.company_profile,
                    order_card=order_card,
                )
                retry_sensitive_reasons = (
                    _sensitive_tone_violations(retry_reply, self.company_profile) if sensitive_occasion else []
                )
                if retry_sensitive_reasons:
                    retry_safety = SafetyResult(
                        is_safe=False,
                        reasons=[*retry_safety.reasons, *retry_sensitive_reasons],
                    )
                if retry_safety.is_safe:
                    return ConversationAction(
                        kind="send",
                        messages=_finalize_messages(retry_reply, sensitive_occasion=sensitive_occasion, company_profile=self.company_profile),
                        risk_level=risk_level,
                        safety_triggered_reasons=triggered_reasons,
                        safety_retry_succeeded=True,
                    )
                safety = retry_safety
            except LLMError:
                pass
            fallback = _fallback_after_safety_failure(
                next_step,
                order_card=order_card if isinstance(order_card, OrderCard) else None,
                recent_messages=recent_messages,
                stock_context=stock_context,
                company_profile=self.company_profile,
                risk_category=risk.category,
                latest_text=last_client_text,
                budget_options=budget_options,
            )
            if fallback:
                return ConversationAction(
                    kind="send",
                    messages=_finalize_messages(fallback, sensitive_occasion=sensitive_occasion, company_profile=self.company_profile),
                    risk_level=risk_level,
                    safety_reasons=safety.reasons,
                    risk_category=risk.category,
                    safety_triggered_reasons=triggered_reasons,
                    safety_retry_succeeded=False,
                    next_step=next_step.code,
                    order_patch=_action_patch_for_next_step(next_step.code),
                )
            return ConversationAction(
                kind="human_review",
                messages=["Передам менеджеру, чтобы точно проверить и ответить вам корректно."],
                risk_level=risk_level,
                safety_reasons=safety.reasons,
                risk_category=risk.category,
                safety_triggered_reasons=triggered_reasons,
                safety_retry_succeeded=False,
            )

        return ConversationAction(
            kind="send",
            messages=_finalize_messages(reply, sensitive_occasion=sensitive_occasion, company_profile=self.company_profile),
            risk_level=risk_level,
            **action_metadata,
        )

    async def _retry_or_fallback_after_parse_failure(
        self,
        *,
        prompt: str,
        next_step,
        order_card: OrderCard | None,
        recent_messages: list[str],
        stock_context: str | None,
        risk_level: RiskLevel,
        sensitive_occasion: bool,
    ) -> ConversationAction | None:
        retry_prompt = (
            prompt
            + "\n\nПредыдущий ответ не удалось разобрать как JSON. "
            + "Верни только корректный JSON формата ModelDecision, без markdown и без текста вне JSON."
        )
        try:
            retry_reply = await generate_with_optional_schema(
                self.llm,
                retry_prompt,
                response_schema=ModelDecision.model_json_schema(),
            )
        except LLMError:
            return None
        retry_decision = parse_model_decision(retry_reply)
        if retry_decision is None:
            return None
        reply = retry_decision.reply
        safety = check_reply_safety(reply, stock_context=stock_context, company_profile=self.company_profile, order_card=order_card)
        sensitive_tone_reasons = _sensitive_tone_violations(reply, self.company_profile) if sensitive_occasion else []
        if sensitive_tone_reasons:
            safety = SafetyResult(is_safe=False, reasons=[*safety.reasons, *sensitive_tone_reasons])
        if not safety.is_safe:
            return ConversationAction(
                kind="human_review",
                messages=["Передам менеджеру, чтобы точно проверить и ответить вам корректно."],
                risk_level=risk_level,
                safety_reasons=["parse_failed"],
                safety_triggered_reasons=safety.reasons,
                safety_retry_succeeded=False,
            )
        if retry_decision.needs_human:
            return ConversationAction(
                kind="human_review",
                messages=_finalize_messages(reply, sensitive_occasion=sensitive_occasion, company_profile=self.company_profile),
                risk_level=risk_level,
                safety_reasons=["parse_failed", "model_decision_needs_human"],
                order_patch=dict(retry_decision.case_patch),
                intent=retry_decision.intent,
                next_step=retry_decision.next_step,
                confidence=retry_decision.confidence,
                safety_retry_succeeded=True,
            )
        return ConversationAction(
            kind="send",
            messages=_finalize_messages(reply, sensitive_occasion=sensitive_occasion, company_profile=self.company_profile),
            risk_level=risk_level,
            safety_reasons=["parse_failed"],
            order_patch=dict(retry_decision.case_patch),
            intent=retry_decision.intent,
            next_step=retry_decision.next_step,
            confidence=retry_decision.confidence,
            safety_retry_succeeded=True,
        )



def _fallback_after_safety_failure(
    next_step: NextStep,
    *,
    order_card: OrderCard | None,
    recent_messages: list[str],
    stock_context: str | None,
    company_profile: CompanyProfile,
    risk_category: RiskCategory,
    latest_text: str,
    budget_options: BudgetOptions | list[BudgetOption] | None = None,
) -> str | None:
    cautious = _cautious_reply_for_medium_risk(
        risk_category,
        stock_context=stock_context,
        latest_text=latest_text,
        company_profile=company_profile,
    )
    if cautious:
        return cautious
    return deterministic_order_reply(
        next_step,
        order_card,
        recent_messages=recent_messages,
        stock_context=stock_context or "",
        company_profile=company_profile,
        budget_options=budget_options,
    )


def _is_budget_unknown_answer(text: str) -> bool:
    return is_budget_unknown_answer(text)

def _is_upsell_decline(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return bool(re.search(r"\b(?:нет|не\s+нужно|не\s+надо|без\s+этого|ничего\s+не\s+добавляйте|только\s+букет)\b", normalized))


def _action_patch_for_next_step(next_step: str | None) -> dict[str, object]:
    if next_step == "ask_upsell":
        return {"custom_fields": {"upsell_offered": True}}
    return {}


def _merge_action_patch(left: object, right: dict[str, object]) -> dict[str, object]:
    base = dict(left) if isinstance(left, dict) else {}
    result = {**base, **right}
    if isinstance(base.get("custom_fields"), dict) or isinstance(right.get("custom_fields"), dict):
        result["custom_fields"] = {
            **(base.get("custom_fields") if isinstance(base.get("custom_fields"), dict) else {}),
            **(right.get("custom_fields") if isinstance(right.get("custom_fields"), dict) else {}),
        }
    return result


def _looks_like_model_decision_payload(text: str) -> bool:
    normalized = text.strip().lower()
    if normalized.startswith("{") or normalized.startswith("["):
        return True
    return any(marker in normalized for marker in ('"reply":', '"case_patch":', '"confidence":', '"intent":'))


def _last_client_text(recent_messages: list[str]) -> str:
    if not recent_messages:
        return ""
    last = recent_messages[-1].strip()
    prefix = "Клиент:"
    if last.lower().startswith(prefix.lower()):
        return last[len(prefix):].strip()
    return last


def _is_thanks_only(text: str) -> bool:
    normalized = text.lower().replace("ё", "е").strip(" !?.")
    return normalized in {"спасибо", "спс", "благодарю", "хорошо спасибо", "ок спасибо"}


def _is_photo_only(text: str) -> bool:
    return text.strip().lower() == "[photo]"


def _is_media_only(text: str) -> bool:
    return text.strip().lower() == "[media]"


def _cautious_reply_for_medium_risk(
    category: RiskCategory,
    *,
    stock_context: str | None,
    latest_text: str = "",
    company_profile: CompanyProfile | None = None,
) -> str | None:
    profile = company_profile or load_company_profile("amelia_flowers")
    normalized = latest_text.lower().replace("ё", "е")
    if category == RiskCategory.DISCOUNT:
        if "скид" in normalized:
            return "По скидке уточню у менеджера, чтобы не пообещать лишнего. Могу пока подобрать вариант под ваш бюджет."
        return "Могу подобрать вариант дешевле в том же стиле или упростить состав под ваш бюджет. Какой предел по сумме комфортен?"
    if category == RiskCategory.OUT_OF_AREA_DELIVERY:
        return "По такой доставке лучше уточню у менеджера: зависит от адреса и времени. Напишите, пожалуйста, куда и на когда нужно."
    if category == RiskCategory.STOCK_UNCERTAINTY:
        unavailable_item = _unavailable_stock_item(stock_context)
        if unavailable_item:
            return f"{unavailable_item.capitalize()} сейчас нет. {profile.alternative_offer_text}. Подскажите бюджет, чтобы сориентировать вас."
        if not stock_context:
            return f"По наличию лучше уточню у менеджера, чтобы не пообещать лишнего. {profile.alternative_offer_text}."
    if category == RiskCategory.GUARANTEE_REQUEST:
        return "Уточню у менеджера по наличию и возможности собрать именно такой вариант, чтобы не пообещать лишнего."
    if category == RiskCategory.SENSITIVE_OCCASION:
        return "Понимаю. Подскажите, пожалуйста, бюджет и удобный формат: самовывоз или доставка."
    return None


def _catalog_price_reply_for_question(
    text: str,
    stock_context: str | None,
    *,
    company_profile: CompanyProfile | None = None,
) -> str | None:
    normalized = text.lower().replace("ё", "е")
    if not re.search(r"\b(?:сколько\s+(?:сто\w*|выйд\w*)|цен\w*|почем|за\s+сколько|обойд\w*)\b", normalized):
        return None
    if is_city_delivery_price_question(normalized, company_profile=company_profile):
        profile = company_profile or load_company_profile("amelia_flowers")
        if profile.delivery_city_price is not None and profile.free_delivery_from is not None:
            return (
                f"По городу доставка — {profile.delivery_city_price} ₽. "
                f"От {profile.free_delivery_from} ₽ доставка бесплатная."
            )
    if is_delivery_price_question(normalized):
        return None
    requested_tokens = set(re.findall(r"[а-яa-z]{4,}", normalized))
    if not stock_context:
        return "По цене лучше уточню у менеджера, чтобы не назвать неверно."
    bouquet_cost_question = "букет" in normalized or re.search(r"\b(?:выйд\w*|обойд\w*)\b", normalized)
    for line in stock_context.splitlines():
        match = re.search(r"-\s*(?P<name>[^—-]+)\s*[—-].*?\b(?P<price>\d[\d ]{2,})\s*₽(?:/(?P<unit>\S+))?", line)
        if not match:
            continue
        name = match.group("name").strip().lower().replace("ё", "е")
        name_tokens = set(re.findall(r"[а-яa-z]{4,}", name))
        if _tokens_overlap(requested_tokens, name_tokens):
            price = int(match.group("price").replace(" ", ""))
            if bouquet_cost_question:
                lower = max(0, price - 500)
                return f"По каталогу можно ориентироваться примерно на {lower}–{price} ₽, но состав определяет флорист. Итоговую стоимость подтвердит менеджер."
            unit = match.group("unit") or "шт"
            return f"{match.group('name').strip().capitalize()} по каталогу — {price} ₽/{unit}. Итоговую стоимость букета подтвердит менеджер после состава."
    return "По этой цене лучше уточню у менеджера: в каталоге сейчас нет подтверждённой цены."


def _tokens_overlap(left: set[str], right: set[str]) -> bool:
    for left_token in left:
        for right_token in right:
            if left_token == right_token or left_token.startswith(right_token[:4]) or right_token.startswith(left_token[:4]):
                return True
    return False


def _default_date_choice_reply(profile: CompanyProfile) -> str:
    today = datetime.now(ZoneInfo(profile.timezone_name)).date()
    suggested = today + timedelta(days=profile.default_date_offset_days)
    if profile.default_date_offset_days == 1:
        date_label = "завтра"
    else:
        date_label = suggested.isoformat()
    return profile.default_date_choice_reply_template.format(date=date_label, date_label=date_label)


def _format_order_card_context(
    card: OrderCard,
    *,
    sensitive_occasion: bool = False,
    company_profile: CompanyProfile | None = None,
) -> str:
    profile = company_profile or load_company_profile("amelia_flowers")
    lines: list[str] = []
    if card.fulfillment_type:
        lines.append(f"- Формат: {'доставка' if card.fulfillment_type == 'delivery' else 'самовывоз'}")
    if card.delivery_date:
        lines.append(f"- Дата: {card.delivery_date}")
    if card.delivery_time:
        lines.append(f"- Время: {card.delivery_time}")
    budget_display = format_budget_display(card)
    if budget_display:
        lines.append(f"- Бюджет: {budget_display}")
    if card.colors:
        preferences = _safe_order_preferences_for_prompt(card.colors, sensitive_occasion=sensitive_occasion, profile=profile)
        if preferences:
            lines.append(f"- Пожелания: {', '.join(preferences)}")
    if card.address:
        lines.append(f"- Адрес: {card.address}")
    if card.sender_name or card.sender_phone:
        lines.append(f"- Отправитель: {card.sender_name or 'не указано'}, {card.sender_phone or 'не указано'}")
    if card.recipient_name or card.recipient_phone:
        lines.append(f"- Получатель: {card.recipient_name or 'не указано'}, {card.recipient_phone or 'не указано'}")
    if card.payment_method:
        lines.append(f"- Оплата: {card.payment_method}")
    for key, value in card.custom_fields.items():
        if key.startswith("_"):
            continue
        if value not in (None, "", [], {}):
            lines.append(f"- {key}: {value}")
    return "\n".join(lines) if lines else "- пока пусто"


def _safe_order_preferences_for_prompt(
    preferences: list[str],
    *,
    sensitive_occasion: bool,
    profile: CompanyProfile,
) -> list[str]:
    if not sensitive_occasion:
        return preferences
    forbidden = [word.lower().replace("ё", "е") for word in profile.sensitive_occasion_forbidden_words]
    safe: list[str] = []
    for preference in preferences:
        normalized = preference.lower().replace("ё", "е")
        if any(re.search(rf"\b{re.escape(word)}\w*\b", normalized) for word in forbidden):
            continue
        safe.append(preference)
    if safe:
        return safe
    return ["сдержанная гамма"]


def _is_sensitive_occasion_sticky(card: OrderCard | None) -> bool:
    return bool(card and card.custom_fields.get("occasion_sensitive") is True)


def _has_sensitive_occasion_context(
    recent_messages: list[str],
    *,
    order_card: OrderCard | None,
    company_profile: CompanyProfile,
) -> bool:
    if _is_sensitive_occasion_sticky(order_card):
        return True
    for message in recent_messages:
        risk = assess_risk(_last_client_text([message]), company_profile=company_profile)
        if risk.category == RiskCategory.SENSITIVE_OCCASION:
            return True
    return False


def _sensitive_occasion_patch(category: RiskCategory) -> dict[str, object]:
    if category == RiskCategory.SENSITIVE_OCCASION:
        return {"custom_fields": {"occasion_sensitive": True}}
    return {}


def _sensitive_tone_violations(reply: str, profile: CompanyProfile) -> list[str]:
    normalized_reply = reply.lower().replace("ё", "е")
    violations: list[str] = []
    for word in profile.sensitive_occasion_forbidden_words:
        normalized_word = word.lower().replace("ё", "е")
        if re.search(rf"\b{re.escape(normalized_word)}\w*\b", normalized_reply):
            violations.append(f"запрещённые слова для чувствительного повода: {word}")
    return violations


def _ensure_pickup_address_for_pickup_time(
    reply: str,
    next_step: str | None,
    order_card: OrderCard | None,
    profile: CompanyProfile,
) -> str:
    if next_step != "ask_pickup_time":
        return reply
    if order_card and order_card.fulfillment_type not in (None, "pickup"):
        return reply
    if not profile.pickup_address or profile.pickup_address.lower() in reply.lower():
        return reply
    if "самовывоз" not in reply.lower() and "забрать" not in reply.lower():
        return reply
    return f"{reply.rstrip()} Самовывоз: {profile.pickup_address}."


def _unavailable_stock_item(stock_context: str | None) -> str | None:
    if not stock_context:
        return None
    for line in stock_context.splitlines():
        match = re.match(r"\s*-\s*(?P<name>.+?)\s+[—-]\s*(?:нет|0|недоступно)\s*$", line.strip(), re.IGNORECASE)
        if match:
            return match.group("name").strip()
    return None


def _finalize_messages(
    reply: str,
    *,
    sensitive_occasion: bool = False,
    company_profile: CompanyProfile | None = None,
) -> list[str]:
    messages = split_into_telegram_messages(reply)
    if sensitive_occasion:
        return [suppress_emojis(message) for message in messages]
    return [vary_reply_emoji(message, seed=len(message)) for message in messages]
