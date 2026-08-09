from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from amelia_manager.client_order_summary import format_client_order_summary
from amelia_manager.company_profile import CompanyProfile, load_company_profile
from amelia_manager.deterministic_replies import deterministic_order_reply
from amelia_manager.emoji_variation import vary_reply_emoji
from amelia_manager.humanizer import split_into_telegram_messages
from amelia_manager.intent import is_greeting_only
from amelia_manager.llm_client import LLMError
from amelia_manager.model_decision import parse_model_decision
from amelia_manager.order_card import OrderCard
from amelia_manager.order_policy import get_next_step
from amelia_manager.order_state import extract_order_state
from amelia_manager.prompts import build_manager_prompt
from amelia_manager.risk import RiskCategory, RiskLevel, assess_risk
from amelia_manager.safety import check_reply_safety


class LLM(Protocol):
    async def generate(self, prompt: str) -> str: ...


@dataclass(frozen=True)
class ConversationAction:
    kind: str
    messages: list[str]
    risk_level: RiskLevel
    safety_reasons: list[str] = field(default_factory=list)


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
        risk = assess_risk(last_client_text)
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

        cautious_reply = _cautious_reply_for_medium_risk(risk.category, stock_context=stock_context)
        if cautious_reply:
            return ConversationAction(kind="send", messages=[cautious_reply], risk_level=risk_level)

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

        prompt = build_manager_prompt(
            client_summary=client_summary,
            recent_messages=recent_messages,
            stage=stage,
            risk_level=risk_level,
            next_step_instruction=next_step.instruction,
            stock_context=stock_context,
            company_profile=self.company_profile,
            order_card_context=_format_order_card_context(order_card) if order_card else None,
        )
        try:
            reply = await self.llm.generate(prompt)
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
        safety = check_reply_safety(reply)
        decision = parse_model_decision(reply)
        if decision is not None:
            reply = decision.reply
            if decision.needs_human:
                return ConversationAction(
                    kind="human_review",
                    messages=_finalize_messages(reply),
                    risk_level=risk_level,
                    safety_reasons=["model_decision_needs_human"],
                )
            safety = check_reply_safety(reply)
        if not safety.is_safe:
            try:
                rewrite_prompt = (
                    prompt
                    + "\n\nТвой прошлый ответ нарушил правило безопасности: "
                    + ", ".join(safety.reasons)
                    + "\nПерепиши ответ коротко, естественно и без нарушения. Не объясняй правила."
                )
                retry_reply = await self.llm.generate(rewrite_prompt)
                retry_safety = check_reply_safety(retry_reply)
                if retry_safety.is_safe:
                    return ConversationAction(
                        kind="send",
                        messages=_finalize_messages(retry_reply),
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
            messages=_finalize_messages(reply),
            risk_level=risk_level,
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


def _cautious_reply_for_medium_risk(category: RiskCategory, *, stock_context: str | None) -> str | None:
    if category == RiskCategory.DISCOUNT:
        return "По скидке уточню у менеджера, чтобы не пообещать лишнего. Могу пока подобрать вариант под ваш бюджет."
    if category == RiskCategory.OUT_OF_AREA_DELIVERY:
        return "По такой доставке лучше уточню у менеджера: зависит от адреса и времени. Напишите, пожалуйста, куда и на когда нужно."
    if category == RiskCategory.STOCK_UNCERTAINTY and not stock_context:
        return "По наличию лучше уточню у менеджера, чтобы не пообещать лишнего. Могу предложить близкий вариант по стилю."
    return None


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


def _finalize_messages(reply: str) -> list[str]:
    return [vary_reply_emoji(message, seed=len(message)) for message in split_into_telegram_messages(reply)]
