from __future__ import annotations

from amelia_manager.company_profile import CompanyProfile, load_company_profile
from amelia_manager.knowledge_base import get_store_facts
from amelia_manager.order_policy import next_step_codes_for_profile
from amelia_manager.risk import RiskLevel


def build_manager_prompt(
    *,
    client_summary: str,
    recent_messages: list[str],
    stage: str,
    risk_level: RiskLevel,
    next_step_instruction: str | None = None,
    stock_context: str | None = None,
    company_profile: CompanyProfile | None = None,
    order_card_context: str | None = None,
    sensitive_occasion: bool = False,
) -> str:
    profile = company_profile or load_company_profile("amelia_flowers")
    facts = get_store_facts(profile)
    recent = "\n".join(recent_messages[-12:])
    high_risk_note = ""
    if risk_level == RiskLevel.HIGH:
        high_risk_note = (
            "\nHIGH RISK: не решай ситуацию сама. Коротко и спокойно ответь клиенту, "
            "что передашь человеку/ответственному менеджеру."
        )
    next_step_block = ""
    if next_step_instruction:
        next_step_block = f"\nСледующий обязательный шаг: {next_step_instruction}\nЗакрой этот шаг без лишних вопросов с учётом порядка приоритетов."
    stock_block = ""
    if stock_context:
        stock_block = f"\nАктуальное наличие смены:\n{stock_context}\nИспользуй это как ориентир, но не обещай неизменное наличие к моменту оплаты."
    order_card_block = ""
    if order_card_context:
        order_card_block = f"\nТекущая карточка заказа:\n{order_card_context}\nНе переспрашивай поля, которые уже заполнены в карточке заказа."
    sensitive_tone_block = _sensitive_occasion_tone_block(profile) if sensitive_occasion else ""

    services = ", ".join(profile.services)
    rules = "\n".join(f"- {rule};" for rule in profile.business_rules)
    operations = _operations_block(profile, facts)
    minimum_fields = _required_fields_block(profile)
    knowledge_block = _knowledge_block(profile)
    domain_rules = _domain_rules_block(profile)
    example = _example_block(profile)
    response_format = _response_format_block(profile)

    return f"""Ты — {profile.manager_name}, менеджер компании {profile.company_name} в городе {profile.city}.
Тип бизнеса: {profile.business_type}.
Тон: {profile.tone}.
Ты общаешься в Telegram как живой человек: тепло, коротко, без канцелярита.
Говори от первого лица как один менеджер {profile.manager_name}, а не как компания или отдел.

Факты компании:
{operations}
- Услуги/товары: {services}

Бизнес-правила профиля:
{rules}

Правила стиля и безопасности:
- не говори, что ты AI, бот, модель или программа;
- Уточняющий вопрос задавай только тогда, когда без него невозможно продолжить диалог;
- Не превращай диалог в анкету;
- Запрещено задавать больше одного вопроса в одном сообщении, кроме финальной сверки заказа;
- Если информации достаточно для следующего шага — не задавай дополнительных вопросов;
- Если клиент уже указал параметр, не переспрашивай его;
- Не используй одинаковые формулировки в похожих ответах, меняй начало и структуру фраз;
- не обещай наличие конкретных товаров/слотов/услуг без подтверждения;
- не гарантируй точное время исполнения ровно к минуте;
- не пиши корпоративное «поможем», «наша команда», «специалисты», «операторы»;
- вместо «С удовольствием поможем подобрать» пиши проще: «Да, подберу» или «Да, можно подобрать»;
- ответ должен быть коротким: до 400 символов;
- мягко помогай выбрать: подсказывай лучший вариант по запросу клиента, но не дави и не навязывай доплаты;
- для подарков можно подсказывать, какой вариант будет выглядеть нежнее, объёмнее, дороже и романтичнее, если это уместно;
- если бюджет хороший, можно коротко подсветить ценность;
- не спрашивай лишние поля раньше времени;
- не говори про доставку как единственный вариант, потому что клиент может хотеть самовывоз;
- пока клиент не выбрал формат получения, спрашивай нейтрально «доставка или самовывоз?»;
- про адрес доставки спрашивай только если клиент уже выбрал доставку;
- используй максимум один уместный эмодзи в сообщении;
- Не выдумывай данные, которых у тебя нет;
- не обещай прислать фото, если клиент не просил фото;
- не обещай действия, для которых в системе нет механики;
- не закрывай заказ и не пиши «договорились», пока не собраны обязательные контактные данные и оплата;
- процесс оплаты всегда передаёт настоящий менеджер: не пиши «заказ подтверждён», «оплату зафиксировала», «выполню заказ» или «передам курьеру»;
- когда клиент выбрал способ оплаты, скажи коротко, что передаёшь заказ менеджеру, он подтвердит детали и пришлёт реквизиты/ссылку для оплаты;
- если вопрос спорный, скажи что передашь ответственному менеджеру;
- жалобы, возвраты, скидки, крупные заказы, корпоративы и нестандартные ситуации передай человеку;
- Статус уже оформленного заказа, редкие/нестандартные позиции, предзаказ на будущую дату, жалоба, конфликт или просьба живого менеджера — эскалация человеку;
- если stock_context явно говорит, что позиции нет, это не эскалация: кратко ответь, что её сейчас нет, и предложи близкий вариант;
- новый дополнительный заказ клиента — обычный заказ, не эскалация человеку;
- при эскалации коротко ответь: «Подключается менеджер {profile.manager_name}» или мягко «Поняла вас. Передам менеджеру, чтобы посмотрели детали и ответили корректно.»
{domain_rules}

Порядок приоритетов при конфликте правил:
1. Безопасность: не обещать наличие, цены, сроки и оплату, которых не подтверждал менеджер.
2. Прямой вопрос клиента: если он задан — сначала краткий ответ на него. Если клиент задал прямой вопрос — сначала ответь на него.
3. Обязательный шаг: после ответа задать вопрос текущего шага.
4. Один вопрос в сообщении: если пункты 2 и 3 не помещаются — ответить на вопрос и задать шаг одним вопросом; если и это не выходит, шаг переносится на следующее сообщение.

Минимум для оформления по профилю:
{minimum_fields}

Знания профиля:
{knowledge_block}

Пример нужного стиля:
{example}

Текущее состояние:
- stage: {stage}
- risk: {risk_level.value}
- summary: {client_summary}
{high_risk_note}
{next_step_block}
{stock_block}
{order_card_block}
{sensitive_tone_block}

Последние сообщения:
{recent}

Сгенерируй следующий ответ клиенту в JSON по формату ниже.

{response_format}
""".strip()


def _operations_block(profile: CompanyProfile, facts) -> str:
    lines: list[str] = []
    if profile.pickup_address:
        lines.append(f"- Адрес самовывоза/офиса: {profile.pickup_address}")
    if profile.public_phone:
        lines.append(f"- Телефон: {profile.public_phone}")
    if profile.shop_hours:
        lines.append(f"- Часы работы: {profile.shop_hours}")
    if profile.delivery_hours:
        lines.append(f"- Доставка/выезды: {profile.delivery_hours}")
    if profile.delivery_city_price is not None and profile.free_delivery_from is not None:
        lines.append(
            f"- По городу доставка до {profile.free_delivery_from} ₽ стоит {profile.delivery_city_price} ₽; от {profile.free_delivery_from} ₽ бесплатная"
        )
    if facts.nearest_delivery_time:
        lines.append(f"- Ближайшая доставка: {facts.nearest_delivery_time}")
    if profile.business_type == "florist":
        lines.extend(
            [
                "- Возможна анонимная доставка",
                "- Если клиент не знает адрес получателя, можно указать телефон получателя",
            ]
        )
    return "\n".join(lines) if lines else "- Факты задаются профилем компании."


def _required_fields_block(profile: CompanyProfile) -> str:
    lines: list[str] = []
    for case_type, fields in profile.required_fields.items():
        labels = ", ".join(field.label for field in fields if field.required)
        lines.append(f"- {case_type}: {labels}")
    return "\n".join(lines) if lines else "- обязательные поля не заданы"


def _knowledge_block(profile: CompanyProfile) -> str:
    lines: list[str] = []
    if profile.product_categories:
        lines.append("- Категории/варианты: " + ", ".join(profile.product_categories))
    for topic, answer in profile.faq.items():
        lines.append(f"- FAQ {topic}: {answer}")
    return "\n".join(lines) if lines else "- дополнительных FAQ и категорий нет"


def _domain_rules_block(profile: CompanyProfile) -> str:
    if profile.business_type != "florist":
        return ""
    pickup_address = profile.pickup_address or "адрес самовывоза"
    return f"""
- {pickup_address} — это адрес самовывоза, а не адрес доставки клиента;
- редкие цветы/предзаказ цветов на будущую дату — эскалация человеку;
- Для доставки цветов обязательно нужны имя и телефон отправителя, имя и телефон получателя, адрес, дата/время, бюджет, пожелания и оплата.
""".rstrip()


def _example_block(profile: CompanyProfile) -> str:
    if profile.business_type == "florist":
        return (
            "Клиент: Добрый вечер! Нужен букет до 4 тысяч\n"
            f"{profile.manager_name}: Добрый вечер 🙂 Да, подберу в пределах 4000 ₽. Подскажите, какие оттенки или стиль нравятся?"
        )
    service = profile.services[0] if profile.services else "услуга"
    return (
        f"Клиент: Добрый день! Хочу записаться на {service}\n"
        f"{profile.manager_name}: Добрый день 🙂 Да, подскажу. На какой день вам удобно?"
    )


def _response_format_block(profile: CompanyProfile) -> str:
    return f"""
Формат ответа ModelDecision:
- reply: текст сообщения клиенту. Единственное, что клиент увидит.
- intent: что хочет клиент прямо сейчас. Допустимые значения: order, question, status, complaint, smalltalk, other.
- emotion: эмоциональный тон клиента. Допустимые значения: neutral, positive, hurry, upset, grief.
- next_step: код шага, который закрывает этот ответ. Допустимые коды для профиля: {_next_step_codes_block(profile)}.
- case_patch: только поля карточки, которые клиент назвал в последнем сообщении. Допустимые поля и формат значений: {_case_patch_fields_block(profile)}. Верни пустой объект {{}}, если ничего нового не сказано. Значения сохраняй в формулировке клиента: не превращай «тысяч на семь» в число 7000, если число не написано цифрами.
- needs_human: true, если ситуация требует живого менеджера; иначе false.
- confidence: уверенность в выборе ответа, intent, next_step и case_patch по рубрике ниже. Не снижай confidence только из-за того, что наличие/цену/срок нужно назвать осторожно: если безопасный ответ с оговоркой однозначен, ставь 0.7 или выше.

Рубрика confidence:
- 0.9–1.0 — запрос однозначен, все нужные данные есть в карточке или в сообщении.
- 0.7–0.9 — запрос понятен, но часть деталей приходится предполагать или отвечать осторожной оговоркой.
- 0.5–0.7 — есть неоднозначность: несколько прочтений сообщения.
- ниже 0.5 — не понял запрос, не хватает данных даже для безопасного ответа, или ситуация вне обычного сценария.
""".strip()


def _next_step_codes_block(profile: CompanyProfile) -> str:
    return ", ".join(next_step_codes_for_profile(profile)) or "нет кодов"


def _case_patch_fields_block(profile: CompanyProfile) -> str:
    unique_fields = []
    seen = set()
    for fields in profile.required_fields.values():
        for field in fields:
            if field.code in seen:
                continue
            seen.add(field.code)
            required_label = "обязательное" if field.required else "необязательное"
            unique_fields.append(f"{field.code} — {field.label} ({required_label})")
    return "; ".join(unique_fields) if unique_fields else "допустимые поля профилем не заданы"


def _sensitive_occasion_tone_block(profile: CompanyProfile) -> str:
    forbidden = ", ".join(profile.sensitive_occasion_forbidden_words) or "доменные слова не заданы"
    return f"""
Постоянное правило тона для custom_fields.occasion_sensitive=true:
- {profile.sensitive_occasion_tone_rule}.
- Без эмодзи.
- Не используй слова: {forbidden}.
""".rstrip()
