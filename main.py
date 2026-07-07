import datetime
import json
import math
import os
import random
import re
import threading
from collections import defaultdict
from typing import Any

import telebot
from dotenv import load_dotenv

load_dotenv()

CONFIG = {
    "SHOW_AUTHOR": os.getenv("SHOW_AUTHOR", "1") == "1",
    "DELETE_ORIGINAL": os.getenv("DELETE_ORIGINAL", "1") == "1",
    "SHOW_PRETTY_LINK": os.getenv("SHOW_PRETTY_LINK", "1") == "1",
    "SEND_AS_REPLY": os.getenv("SEND_AS_REPLY", "0") == "1",
    "ATTACH_USER_TEXT": os.getenv("ATTACH_USER_TEXT", "1") == "1",
}

TOKEN = os.getenv("TG_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TG_BOT_TOKEN is not set")

bot = telebot.TeleBot(TOKEN)

# Обработчики выполняются в разных потоках, поэтому общее состояние
# (PARTY_MEMBERS, TAG_MEMBERS, DOMAINS) и запись в файлы защищены одним локом.
STATE_LOCK = threading.Lock()

# ADMIN_IDS сравнивается с id ПОЛЬЗОВАТЕЛЯ (from_user.id), а не чата.
ADMIN_IDS: set[str] = {
    part.strip() for part in os.getenv("ADMIN_IDS", "").split(",") if part.strip()
}

# group(1) — протокол, group(2) — поддомены, group(3) — опциональный kk,
# group(4) — домен, group(5) — путь
URL_PATTERN = re.compile(
    r"(?i)(?<!\w)(https?://)?((?:[\w-]+\.)*)(kk)?(instagram\.com|tiktok\.com|twitter\.com|x\.com)(\S*)"
)

DOMAINS_FILENAME = "domains.json"
TAG_MEMBERS_FILENAME = "tag_members.json"

DEFAULT_DOMAINS = {
    "instagram.com": "instagramkk.com",
    "tiktok.com": "kksav.com",
    "twitter.com": "kksav.com",
    "x.com": "kksav.com",
}

# Через сколько минут после времени готовности инвайт считается протухшим.
PARTY_INVITE_RESET_MINUTES = int(os.getenv("PARTY_INVITE_RESET_MINUTES", "120"))


def load_json(path: str, default: Any) -> Any:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    return default


def save_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


DOMAINS: dict[str, str] = load_json(DOMAINS_FILENAME, dict(DEFAULT_DOMAINS))
if not os.path.exists(DOMAINS_FILENAME):
    save_json(DOMAINS_FILENAME, DOMAINS)

# Ключи чатов — строки, чтобы состояние переживало сериализацию в JSON.
TAG_MEMBERS: dict[str, list[str]] = load_json(TAG_MEMBERS_FILENAME, {})
PARTY_MEMBERS: dict[str, dict[int, tuple[Any, datetime.datetime]]] = defaultdict(dict)


def now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def is_admin(message) -> bool:
    return str(message.from_user.id) in ADMIN_IDS


def parse_ready_time(message) -> datetime.datetime | None:
    """Разбирает опциональное смещение в минутах из команды вида '/accept 15'.

    Нет аргумента -> готов сейчас. Некорректный аргумент -> None.
    """
    args = message.text.split()[1:]
    if not args:
        return now()
    try:
        offset = int(args[0])
    except ValueError:
        return None
    return now() + datetime.timedelta(minutes=offset)


def prune_expired_invites(chat_id: str) -> None:
    """Удаляет протухшие инвайты. Вызывающий должен держать STATE_LOCK."""
    deadline = now() - datetime.timedelta(minutes=PARTY_INVITE_RESET_MINUTES)
    party = PARTY_MEMBERS[chat_id]
    expired = [uid for uid, (_, ready_dt) in party.items() if ready_dt < deadline]
    for uid in expired:
        del party[uid]


def register_accept(message) -> datetime.datetime | None:
    """Добавляет отправителя в состав. Возвращает время готовности либо None,
    если аргумент команды некорректен (в этом случае шлёт подсказку)."""
    ready_dt = parse_ready_time(message)
    if ready_dt is None:
        bot.reply_to(
            message,
            'Использование: "/accept 15" — готов через 15 минут, или "/accept" — готов сейчас',
        )
        return None

    chat_id = str(message.chat.id)
    with STATE_LOCK:
        PARTY_MEMBERS[chat_id][message.from_user.id] = (message.from_user, ready_dt)
        prune_expired_invites(chat_id)
    return ready_dt


def format_party(chat_id: str) -> str:
    with STATE_LOCK:
        prune_expired_invites(chat_id)
        party = list(PARTY_MEMBERS[chat_id].values())

    current = now()
    lines = ["Текущий состав:", f"Количество — ({len(party)})"]
    for player, ready_dt in party:
        name = player.first_name.strip()
        if ready_dt <= current:
            status = "ГОТОВ"
        else:
            minutes = math.ceil((ready_dt - current).total_seconds() / 60)
            status = f"через {minutes} мин"
        lines.append(f"{name} — {status}")
    return "\n".join(lines)


@bot.message_handler(commands=["settaggroup"])
def set_tag_group(message):
    member_ids = message.text.replace("@", "").split()[1:]
    chat_id = str(message.chat.id)
    with STATE_LOCK:
        TAG_MEMBERS[chat_id] = member_ids
        save_json(TAG_MEMBERS_FILENAME, TAG_MEMBERS)
    bot.reply_to(
        message,
        f"Tag group for this chat is set. {len(member_ids)} members: "
        f"{', '.join(member_ids) or '—'}",
    )


@bot.message_handler(commands=["dota"])
def dota(message):
    if register_accept(message) is None:
        return

    chat_id = str(message.chat.id)
    tags = ["@" + member for member in TAG_MEMBERS.get(chat_id, [])]
    random.shuffle(tags)

    parts = [
        "Вы были приглашены в Dota 2!",
        "",
        '<a href="tg://bot_command?command=accept">ПРИНЯТЬ ПРИГЛАШЕНИЕ</a>',
        format_party(chat_id),
    ]
    if tags:
        parts += ["", "", " ".join(tags)]

    bot.send_message(chat_id=message.chat.id, text="\n".join(parts), parse_mode="HTML")


@bot.message_handler(commands=["accept"])
def accept_dota_party(message):
    ready_dt = register_accept(message)
    if ready_dt is None:
        return

    name = message.from_user.first_name.strip()
    if ready_dt <= now():
        accept_text = f"{name} готов убивать нубиков"
    else:
        minutes = math.ceil((ready_dt - now()).total_seconds() / 60)
        accept_text = f"{name} будет готов убивать нубиков через {minutes} мин"

    parts = [accept_text, "", format_party(str(message.chat.id))]
    bot.send_message(chat_id=message.chat.id, text="\n".join(parts), parse_mode="HTML")


@bot.message_handler(commands=["party"])
def party(message):
    bot.send_message(
        chat_id=message.chat.id,
        text=format_party(str(message.chat.id)),
        parse_mode="HTML",
    )


@bot.message_handler(commands=["announce"])
def announce(message):
    if not is_admin(message):
        bot.reply_to(message, "Nah broski, you are not an admin")
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(message, "Использование: /announce <chat_id> <текст>")
        return

    _, chat_id, text = parts
    try:
        bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    except Exception as e:
        bot.reply_to(message, f"Не удалось отправить: {e}")


@bot.message_handler(commands=["setdomain"])
def set_domain(message):
    if not is_admin(message):
        bot.reply_to(message, "Nah broski, you are not an admin")
        return

    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(
            message, "Использование: /setdomain <original_domain> <preview_domain>"
        )
        return

    original_domain = parts[1].lower()
    preview_domain = parts[2].lower()
    if original_domain not in DOMAINS:
        bot.reply_to(
            message,
            f"Домен {original_domain} не поддерживается. Доступно: {', '.join(DOMAINS)}",
        )
        return

    with STATE_LOCK:
        DOMAINS[original_domain] = preview_domain
        save_json(DOMAINS_FILENAME, DOMAINS)
    bot.reply_to(message, f"Домен {original_domain} → {preview_domain}")


@bot.message_handler(content_types=["text"])
def replace_links(message):
    match = URL_PATTERN.search(message.text)
    if not match:
        return

    protocol = match.group(1) or "https://"
    subdomains = match.group(2) or ""
    # group(3) — kk, при построении URL не используется
    main_domain = match.group(4).lower()
    path = match.group(5) or ""

    preview_domain = DOMAINS.get(main_domain)
    if preview_domain is None:
        return

    path_no_args = path.split("?")[0]

    # Превью-ссылка — на превью-домен без поддоменов оригинала
    # (иначе получаются несуществующие хосты вроде vm.kksav.com).
    preview_url = f"{protocol}{preview_domain}{path}"
    # Оригинальная ссылка — с поддоменами, чтобы реально открывалась.
    original_url = f"{protocol}{subdomains}{main_domain}{path}"
    pretty_link_text = f"{main_domain}{path_no_args}".rstrip("/")

    hidden_preview = f'<a href="{preview_url}">&#8203;</a>'

    body_parts: list[str] = []

    if CONFIG["ATTACH_USER_TEXT"]:
        # Вырезаем только совпавшую ссылку, остальной текст (в т.ч. вторую
        # ссылку) сохраняем, чтобы ничего не терять.
        leftover = message.text[: match.start()] + message.text[match.end() :]
        leftover = re.sub(r"[ \t]+", " ", leftover)
        leftover = re.sub(r"\n{3,}", "\n\n", leftover).strip()
        if leftover:
            body_parts.append(leftover)

    meta: list[str] = []
    if CONFIG["SHOW_PRETTY_LINK"]:
        meta.append(f'<a href="{original_url}">🔗 {pretty_link_text}</a>')

    if CONFIG["SHOW_AUTHOR"] and message.chat.type != "private":
        user = message.from_user
        full_name = f"{user.first_name} {user.last_name or ''}".strip()
        meta.append(f'<a href="tg://user?id={user.id}">👤 {full_name}</a>')

    if meta:
        body_parts.append("\n".join(meta))

    final_text = hidden_preview + "\n\n".join(body_parts)
    reply_to = message.message_id if CONFIG["SEND_AS_REPLY"] else None

    try:
        bot.send_message(
            chat_id=message.chat.id,
            text=final_text,
            parse_mode="HTML",
            reply_to_message_id=reply_to,
        )
        if CONFIG["DELETE_ORIGINAL"]:
            bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    print("Бот запущен")
    bot.infinity_polling()
