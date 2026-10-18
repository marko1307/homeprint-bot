import os
import json
import html
import logging
import random
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
FETCHLAYER_API_KEY = os.environ["FETCHLAYER_API_KEY"]

API_BASE = "https://api.fetchlayer.dev/makerworld"
STATE_FILE = Path("posted.json")

SEARCH_TERMS = [
    "home organization",
    "desk organizer",
    "cable holder",
    "kitchen organizer",
    "storage box",
    "wall hook",
    "drawer organizer",
    "bathroom organizer",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {FETCHLAYER_API_KEY}",
    "Content-Type": "application/json",
    "User-Agent": "HomePrintBot/1.0",
})


def load_posted():
    try:
        return set(json.loads(STATE_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def save_posted(posted):
    STATE_FILE.write_text(
        json.dumps(sorted(posted), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def fetchlayer_post(endpoint, payload):
    response = session.post(
        f"{API_BASE}/{endpoint}",
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def search_models(term):
    data = fetchlayer_post("search-models", {
        "query": term,
        "sortBy": "trending",
        "printableOnly": True,
        "limit": 20,
    })
    return data.get("models", [])


def get_model_details(model_id):
    data = fetchlayer_post("model-detail", {
        "model": str(model_id),
        "printProfileLimit": 20,
    })
    return data.get("model", {})


def clean_description(raw):
    if not raw:
        return ""
    text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def format_print_time(seconds):
    if not seconds:
        return "нет данных"

    hours = int(seconds) // 3600
    minutes = (int(seconds) % 3600) // 60

    if hours and minutes:
        return f"{hours} ч {minutes} мин"
    if hours:
        return f"{hours} ч"
    return f"{minutes} мин"


def make_caption(title, description, url, profile):
    parts = [
        f"🏠 <b>{html.escape(title)}</b>",
        "",
    ]

    if description:
        parts += [html.escape(description[:450]), ""]

    if profile:
        print_time = format_print_time(profile.get("printTimeSeconds"))
        grams = profile.get("filamentGrams")

        parts.append(f"⏱ Время печати: {html.escape(print_time)}")
        if grams is not None:
            parts.append(f"🧵 Расход пластика: {html.escape(str(grams))} г")
        else:
            parts.append("🧵 Расход пластика: нет данных")
    else:
        parts.append("⏱ Время печати: нет данных")
        parts.append("🧵 Расход пластика: нет данных")

    safe_url = html.escape(url, quote=True)
    parts += [
        "",
        f'🔗 <a href="{safe_url}">Открыть модель на MakerWorld</a>',
        "",
        "#3Dпечать #ПолезныеВещи #MakerWorld",
    ]

    caption = "\n".join(parts)
    return caption[:1000]


def publish(model, details):
    title = model.get("title", "Модель MakerWorld")
    url = model.get("modelUrl", "")
    image = model.get("coverUrl", "")

    if not title or not url or not image:
        raise ValueError("В результате поиска не хватает названия, ссылки или обложки")

    description = clean_description(details.get("description", ""))

    profiles = details.get("printProfiles") or []
    profile = profiles[0] if profiles else None

    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    response = session.post(api_url, data={
        "chat_id": CHANNEL_ID,
        "photo": image,
        "caption": make_caption(title, description, url, profile),
        "parse_mode": "HTML",
    }, timeout=40)

    if not response.ok:
        logging.error("Telegram sendPhoto error: %s", response.text)

    response.raise_for_status()
    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")
        
def main():
    posted = load_posted()
    term = random.choice(SEARCH_TERMS)
    logging.info("Searching FetchLayer for: %s", term)

    try:
        models = search_models(term)
    except Exception:
        logging.exception("FetchLayer search failed")
        return

    for model in models:
        url = model.get("modelUrl")
        model_id = model.get("modelId")

        if not url or not model_id or url in posted:
            continue

        try:
            details = get_model_details(model_id)
            publish(model, details)
            posted.add(url)
            save_posted(posted)
            logging.info("Published: %s", model.get("title"))
            return
        except Exception:
            logging.exception("Could not publish model: %s", url)
            return

    logging.info("No new model found. No post sent.")       
if __name__ == "__main__":
        main()
