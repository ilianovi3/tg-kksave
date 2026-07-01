import json
import os
import random
import re
from pathlib import Path

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

# group(1) - протокол, group(2) - поддомены, group(3) - опциональный kk, group(4) - домен, group(5) - путь
URL_PATTERN = re.compile(
    r"(?i)(?<!\w)(https?://)?((?:[\w-]+\.)*)(kk)?(instagram\.com|tiktok\.com|twitter\.com|x\.com)(\S*)"
)
ADMIN_IDS = os.getenv("ADMIN_IDS", "").split(",")
DOMAINS_FILENAME = "domains.json"
if Path(DOMAINS_FILENAME).exists():
    with open(DOMAINS_FILENAME, "r") as f:
        DOMAINS = json.load(f)
else:
    DOMAINS = {
        "instagram.com": "kksav.com",
        "tiktok.com": "kksav.com",
        "twitter.com": "kksav.com",
        "x.com": "kksav.com",
    }
    with open(DOMAINS_FILENAME, "w") as f:
        json.dump(DOMAINS, f, indent=4)


TAG_MEMBERS: dict[str, list[str]] = {}


def format_member_ids_to_tag(members: list[str]) -> str:
    return " ".join(["@" + member for member in members])


@bot.message_handler(commands=["settaggroup"])
def settaggroup(message):
    member_ids = message.text.strip().replace("@", "").split()[1:]
    TAG_MEMBERS[message.chat.id] = member_ids
    bot.reply_to(
        message,
        f"Tag group for this chat is set. {len(member_ids)} members: {', '.join(member_ids)}",
    )


@bot.message_handler(commands=["dota"])
def dota(message):
    user_tags = format_member_ids_to_tag(TAG_MEMBERS[message.chat.id])
    random.shuffle(user_tags)
    response_text = f"Вы были приглашены в Защиту Древних 2!\n{user_tags}"
    bot.send_message(chat_id=message.chat.id, text=response_text, parse_mode="HTML")


@bot.message_handler(commands=["announce"])
def announce(message):
    if str(message.chat.id) not in ADMIN_IDS:
        bot.reply_to(message, "Nah broski, you are not an admin")
        return

    user_message = message.text.strip()
    chat_id = user_message.split(" ")[1]
    message_text = " ".join(user_message.split(" ")[2:])

    bot.send_message(chat_id=chat_id, text=message_text, parse_mode="HTML")


@bot.message_handler(commands=["setdomain"])
def set_domain(message):
    if str(message.chat.id) not in ADMIN_IDS:
        bot.reply_to(message, "Nah broski, you are not an admin")
        return
    user_message = message.text.strip()
    parts = user_message.split(" ")
    if len(parts) != 3:
        bot.reply_to(message, "Usage: /setdomain <original_domain> <preview_domain>")
        return

    original_domain = parts[1].lower()
    preview_domain = parts[2].lower()
    if original_domain not in DOMAINS:
        bot.reply_to(
            message,
            f"Domain {original_domain} is not supported. Options: {', '.join(DOMAINS.keys())}",
        )
        return
    DOMAINS[original_domain] = preview_domain
    bot.reply_to(message, f"Domain {original_domain} updated to {preview_domain}")


@bot.message_handler(content_types=["text"])
def replace_links(message):
    match = URL_PATTERN.search(message.text)
    if not match:
        return

    raw_protocol = match.group(1)
    fixed_protocol = raw_protocol if raw_protocol else "https://"

    subdomains = match.group(2) if match.group(2) else ""
    # group(3) — это kk, нам оно не нужно при построении URL
    main_domain = match.group(4).lower()
    preview_domain = DOMAINS[main_domain]

    path = match.group(5) if match.group(5) else ""

    path_no_args = path.split("?")[0]

    # Превью-ссылка — всегда с kk
    hidden_url = f"{fixed_protocol}{subdomains}{preview_domain}{path}"

    # Оригинальная ссылка — всегда без kk
    full_original_url = f"{fixed_protocol}{subdomains}{main_domain}{path}"

    # Красивый текст — без протокола и поддоменов
    pretty_link_text = f"{main_domain}{path_no_args}".rstrip("/")

    hidden_url_preview = f'<a href="{hidden_url}">&#8203;</a>'

    user_message = ""
    if CONFIG["ATTACH_USER_TEXT"]:
        user_message = URL_PATTERN.sub("", message.text).strip()

    pretty_url = ""
    if CONFIG["SHOW_PRETTY_LINK"]:
        pretty_url = f'<a href="{full_original_url}">🔗 {pretty_link_text}</a>'

    author = ""
    if CONFIG["SHOW_AUTHOR"] and message.chat.type != "private":
        user = message.from_user
        full_name = (
            f"{user.first_name} {user.last_name if user.last_name else ''}".strip()
        )
        author = f'<a href="tg://user?id={user.id}">👤 {full_name}</a>'

    parts = [
        user_message + "\n" if user_message else None,
        pretty_url if pretty_url else None,
        author if author else None,
    ]
    parts = [part for part in parts if part is not None]
    final_text = hidden_url_preview + "\n".join(parts)
    final_text = final_text.replace("\n" * 3, "\n" * 2).strip().strip("\n")

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
    print("🚀 Бот запущен")
    bot.infinity_polling()
