import os
import json
import re
import html
import logging
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
BASE_URL = "https://makerworld.com"
STATE_FILE = Path("posted.json")
MAX_POSTS_PER_RUN = 1

SEARCH_TERMS = [
    "home organization", "desk organizer", "cable holder",
    "kitchen organizer", "storage box", "wall hook",
    "drawer organizer", "bathroom organizer",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; HomePrintBot/1.0; respectful crawler)"})


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


def get_soup(url):
    response = session.get(url, timeout=25)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def find_model_urls(term):
    # This URL/HTML structure may change; test it before enabling scheduled posts.
    search_url = f"{BASE_URL}/en/search/models?keyword={quote(term)}"
    soup = get_soup(search_url)
    urls = []
    for a in soup.select("a[href]"):
        absolute = urljoin(BASE_URL, a.get("href", ""))
        parsed = urlparse(absolute)
        if parsed.netloc not in {"makerworld.com", "www.makerworld.com"}:
            continue
        if re.search(r"/models/\d+", parsed.path):
            clean = absolute.split("?")[0].split("#")[0]
            if clean not in urls:
                urls.append(clean)
    return urls


def meta(soup, *names):
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return ""


def extract_model(url):
    soup = get_soup(url)
    title = meta(soup, "og:title", "twitter:title")
    image = meta(soup, "og:image", "twitter:image")
    description = meta(soup, "og:description", "description")
    if not title or not image:
        return None
    title = re.sub(r"\s+", " ", html.unescape(title)).strip()
    description = re.sub(r"\s+", " ", html.unescape(description)).strip()
    if len(title) < 4 or not image.startswith(("https://", "http://")):
        return None

    # Do not guess print stats from arbitrary page text. Populate only if
    # verified structured fields are added after checking MakerWorld's current markup.
    return {
        "title": title,
        "image": image,
        "description": description[:500],
        "url": url,
        "time": None,
        "weight": None,
    }


def make_caption(model):
    title = html.escape(model["title"])
    description = html.escape(model["description"])
    link = html.escape(model["url"], quote=True)
    parts = [f"🏠 <b>{title}</b>", ""]
    if description:
        parts += [description, ""]
    parts.append("⏱ Время печати: нет подтверждённых данных")
    parts.append("🧵 Расход пластика: нет подтверждённых данных")
    parts += ["", f'🔗 <a href="{link}">Открыть модель на MakerWorld</a>', "",
              "#3Dпечать #ПолезныеВещи #MakerWorld"]
    caption = "\n".join(parts)
    return caption[:1000] if len(caption) <= 1024 else caption[:1000] + "…"


def publish(model):
    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    response = session.post(api_url, data={
        "chat_id": CHANNEL_ID,
        "photo": model["image"],
        "caption": make_caption(model),
        "parse_mode": "HTML",
    }, timeout=40)
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")


def main():
    posted = load_posted()
    for term in SEARCH_TERMS:
        try:
            urls = find_model_urls(term)
        except Exception as exc:
            logging.warning("Search failed for %r: %s", term, exc)
            continue
        for url in urls:
            if url in posted:
                continue
            try:
                model = extract_model(url)
                if not model:
                    continue
                publish(model)
                posted.add(url)
                save_posted(posted)
                logging.info("Published: %s", model["title"])
                return
            except Exception as exc:
                logging.warning("Could not publish %s: %s", url, exc)
    logging.info("No new model found. No post sent.")


if __name__ == "__main__":
    main()
