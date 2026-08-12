from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Protocol

from amelia_manager.client_order_summary import format_client_order_summary
from amelia_manager.company_profile import CompanyProfile, load_company_profile
from amelia_manager.deterministic_replies import deterministic_order_reply
from amelia_manager.emoji_variation import vary_reply_emoji
from amelia_manager.humanizer import split_into_telegram_messages, suppress_emojis
from amelia_manager.intent import is_greeting_only
from amelia_manager.llm_client import LLMError
from amelia_manager.model_decision import ModelDecision, parse_model_decision
from amelia_manager.order_card import OrderCard
from amelia_manager.order_policy import get_next_step
from amelia_manager.order_state import extract_order_state
from amelia_manager.prompts import build_manager_prompt
from amelia_manager.risk import RiskCategory, RiskLevel, assess_risk
from amelia_manager.safety import SafetyResult, check_reply_safety
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
            )

        catalog_price_reply = _catalog_price_reply_for_question(last_client_text, stock_context)
        if catalog_price_reply:
            return ConversationAction(kind="send", messages=[catalog_price_reply], risk_level=risk_level)

        cautious_reply = _cautious_reply_for_medium_risk(
            risk.category,
            stock_context=stock_context,
            company_profile=self.company_profile,
        )
        if cautious_reply:
            order_patch = _sensitive_occasion_patch(risk.category)
            return ConversationAction(kind="send", messages=[cautious_reply], risk_level=risk_level, order_patch=order_patch)

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
                )
            return ConversationAction(
                kind="send",
                messages=[format_client_order_summary(order_card, company_profile=self.company_profile)],
                risk_level=risk_level,
            )

        order_state = order_card or extract_order_state(recent_messages)
        next_step = get_next_step(order_state, company_profile=self.company_profile)

        sensitive_occasion = _has_sensitive_occasion_context(
            recent_messages,
            order_card=order_card,
            company_profile=self.company_profile,
        )

        prompt = build_manager_prompt(
            client_summary=client_summary,
            recent_messages=recent_messages,
            stage=stage,
            risk_level=risk_level,
            next_step_instruction=next_step.instruction,
            stock_context=stock_context,
            company_profile=self.company_profile,
            order_card_context=_format_order_card_context(order_card) if order_card else None,
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
                stock_context=stock_context,
                company_profile=self.company_profile,
            )
            if fallback:
                return ConversationAction(
                    kind="send",
                    messages=[fallback],
                    risk_level=risk_level,
                    safety_reasons=["llm_error_fallback"],
                )
            return ConversationAction(
                kind="human_review",
                messages=["Сейчас передам менеджеру, чтобы вам ответили по заказу корректно."],
                risk_level=risk_level,
                safety_reasons=["llm_error"],
            )
        safety = check_reply_safety(reply, stock_context=stock_context)
        decision = parse_model_decision(reply)
        action_metadata: dict[str, object] = {}
        if decision is not None:
            reply = decision.reply
            action_metadata = {
                "order_patch": dict(decision.case_patch),
                "intent": decision.intent,
                "next_step": decision.next_step,
                "confidence": decision.confidence,
            }
            reply = _ensure_pickup_address_for_pickup_time(reply, decision.next_step, order_card, self.company_profile)
            if decision.confidence is not None and decision.confidence < 0.5:
                return ConversationAction(
                    kind="human_review",
                    messages=["Передам менеджеру, чтобы точно проверить и ответить вам корректно."],
                    risk_level=risk_level,
                    safety_reasons=["low_model_confidence"],
                    intent=decision.intent,
                    next_step=decision.next_step,
                    confidence=decision.confidence,
                )
            if decision.needs_human:
                return ConversationAction(
                    kind="human_review",
                    messages=_finalize_messages(reply, sensitive_occasion=sensitive_occasion, company_profile=self.company_profile),
                    risk_level=risk_level,
                    safety_reasons=["model_decision_needs_human"],
                    **action_metadata,
                )
            safety = check_reply_safety(reply, stock_context=stock_context)
        sensitive_tone_reasons = _sensitive_tone_violations(reply, self.company_profile) if sensitive_occasion else []
        if sensitive_tone_reasons:
            safety = SafetyResult(is_safe=False, reasons=[*safety.reasons, *sensitive_tone_reasons])
        if not safety.is_safe:
            try:
                rewrite_prompt = (
                    prompt
                    + "\n\nТвой прошлый ответ нарушил правило безопасности: "
                    + ", ".join(safety.reasons)
                    + "\nПерепиши ответ коротко, естественно и без нарушения. Не объясняй правила."
                )
                retry_reply = await generate_with_optional_schema(
                    self.llm,
                    rewrite_prompt,
                    response_schema=ModelDecision.model_json_schema(),
                )
                retry_decision = parse_model_decision(retry_reply)
                if retry_decision is not None:
                    retry_reply = retry_decision.reply
                    if retry_decision.needs_human:
                        return ConversationAction(
                            kind="human_review",
                            messages=_finalize_messages(retry_reply, sensitive_occasion=sensitive_occasion, company_profile=self.company_profile),
                            risk_level=risk_level,
                            safety_reasons=["model_decision_needs_human"],
                        )
                retry_safety = check_reply_safety(retry_reply, stock_context=stock_context)
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
                    )
                safety = retry_safety
            except LLMError:
                safety = safety
            return ConversationAction(
                kind="human_review",
                messages=["Передам менеджеру, чтобы точно проверить и ответить вам корректно."],
                risk_level=risk_level,
                safety_reasons=safety.reasons,
            )

        return ConversationAction(
            kind="send",
            messages=_finalize_messages(reply, sensitive_occasion=sensitive_occasion, company_profile=self.company_profile),
            risk_level=risk_level,
            **action_metadata,
        )


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
    company_profile: CompanyProfile | None = None,
) -> str | None:
    profile = company_profile or load_company_profile("amelia_flowers")
    if category == RiskCategory.DISCOUNT:
        return "По скидке уточню у менеджера, чтобы не пообещать лишнего. Могу пока подобрать вариант под ваш бюджет."
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


def _catalog_price_reply_for_question(text: str, stock_context: str | None) -> str | None:
    normalized = text.lower().replace("ё", "е")
    if not re.search(r"\b(?:сколько\s+сто\w*|цен\w*|почем|за\s+сколько)\b", normalized):
        return None
    requested_tokens = set(re.findall(r"[а-яa-z]{4,}", normalized))
    if not stock_context:
        return "По цене лучше уточню у менеджера, чтобы не назвать неверно."
    for line in stock_context.splitlines():
        match = re.search(r"-\s*(?P<name>[^—-]+)\s*[—-].*?\b(?P<price>\d[\d ]{2,})\s*₽(?:/(?P<unit>\S+))?", line)
        if not match:
            continue
        name = match.group("name").strip().lower().replace("ё", "е")
        name_tokens = set(re.findall(r"[а-яa-z]{4,}", name))
        if requested_tokens & name_tokens:
            price = match.group("price").replace(" ", "")
            unit = match.group("unit") or "шт"
            return f"{match.group('name').strip().capitalize()} по каталогу — {price} ₽/{unit}. Итоговую стоимость букета подтвердит менеджер после состава."
    return "По этой цене лучше уточню у менеджера: в каталоге сейчас нет подтверждённой цены."


def _format_order_card_context(card: OrderCard) -> str:
    lines: list[str] = []
    if card.fulfillment_type:
        lines.append(f"- Формат: {'доставка' if card.fulfillment_type == 'delivery' else 'самовывоз'}")
    if card.delivery_date:
        lines.append(f"- Дата: {card.delivery_date}")
    if card.delivery_time:
        lines.append(f"- Время: {card.delivery_time}")
    if card.budget:
        lines.append(f"- Бюджет: {card.budget} ₽")
    if card.colors:
        lines.append(f"- Пожелания: {', '.join(card.colors)}")
    if card.address:
        lines.append(f"- Адрес: {card.address}")
    if card.sender_name or card.sender_phone:
        lines.append(f"- Отправитель: {card.sender_name or 'не указано'}, {card.sender_phone or 'не указано'}")
    if card.recipient_name or card.recipient_phone:
        lines.append(f"- Получатель: {card.recipient_name or 'не указано'}, {card.recipient_phone or 'не указано'}")
    if card.payment_method:
        lines.append(f"- Оплата: {card.payment_method}")
    for key, value in card.custom_fields.items():
        if value not in (None, "", [], {}):
            lines.append(f"- {key}: {value}")
    return "\n".join(lines) if lines else "- пока пусто"


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
    if next_step != "ask_pickup_time" or not order_card or order_card.fulfillment_type != "pickup":
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
