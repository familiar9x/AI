from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Optional, Any
import re
import time

import feedparser
from bs4 import BeautifulSoup

# Basic VN sentiment lexicon (very simple for Level 1)
POS_WORDS = {"tăng", "tích cực", "lợi nhuận", "bứt phá", "kỷ lục", "mở rộng", "hợp tác", "thặng dư"}
NEG_WORDS = {"giảm", "tiêu cực", "thua lỗ", "điều tra", "xử phạt", "khởi tố", "đình chỉ", "suy giảm", "rủi ro"}

TOPIC_RULES = {
    "KQKD": {"lợi nhuận", "doanh thu", "kết quả kinh doanh", "bctc", "quý", "năm"},
    "Vĩ mô/Chính sách": {"lãi suất", "tỷ giá", "nghị định", "thông tư", "chính sách", "thuế"},
    "Pháp lý": {"khởi tố", "xử phạt", "điều tra", "vi phạm"},
    "M&A/Đầu tư": {"mua lại", "sáp nhập", "thoái vốn", "đầu tư", "phát hành"},
}

TICKER_RE = re.compile(r"\b[A-Z]{2,5}\b")


@dataclass
class NewsItem:
    title: str
    link: str
    published: str
    summary: str
    sentiment: str
    topic: str
    tickers: List[str]


def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "lxml")
    return soup.get_text(" ", strip=True)


def _sentiment(text: str) -> str:
    t = (text or "").lower()
    pos = sum(1 for w in POS_WORDS if w in t)
    neg = sum(1 for w in NEG_WORDS if w in t)
    if pos > neg and pos > 0:
        return "positive"
    if neg > pos and neg > 0:
        return "negative"
    return "neutral"


def _topic(text: str) -> str:
    t = (text or "").lower()
    for topic, kws in TOPIC_RULES.items():
        if any(kw in t for kw in kws):
            return topic
    return "Khác"


def _extract_tickers(text: str) -> List[str]:
    # naive: find uppercase tokens 2-5 chars
    found = set(TICKER_RE.findall(text or ""))
    # filter common noise tokens if needed
    noise = {"USD", "VND", "VN", "CEO", "CFO"}
    return sorted([x for x in found if x not in noise])


def load_sources(path: str) -> List[str]:
    sources = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    sources.append(line)
    except FileNotFoundError:
        pass
    return sources


def fetch_rss_items(sources: List[str], limit_per_source: int = 20) -> List[NewsItem]:
    items: List[NewsItem] = []
    for src in sources:
        d = feedparser.parse(src)
        for e in d.entries[:limit_per_source]:
            title = e.get("title", "")
            link = e.get("link", "")
            published = e.get("published", e.get("updated", ""))
            summary = _clean_html(e.get("summary", "") or e.get("description", ""))

            text = f"{title}. {summary}"
            items.append(
                NewsItem(
                    title=title,
                    link=link,
                    published=published,
                    summary=summary[:4000],
                    sentiment=_sentiment(text),
                    topic=_topic(text),
                    tickers=_extract_tickers(text),
                )
            )
    # naive dedup by link/title
    dedup = {}
    for it in items:
        k = it.link or it.title
        dedup[k] = it
    return list(dedup.values())
