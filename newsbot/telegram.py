from __future__ import annotations

import html
import json
from typing import Any

import httpx


FINANCIAL_FOOTER = "\n\nNot financial advice."


class TelegramClient:
    def __init__(self, token: str | None, chat_id: str | None) -> None:
        self.token = token
        self.chat_id = chat_id

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    async def send_message(self, text: str) -> None:
        if not self.configured:
            raise RuntimeError("Telegram is not configured")
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                data={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": "false",
                },
            )
            response.raise_for_status()


def format_cluster_alert(cluster: Any, documents: list[Any]) -> str:
    summary = json.loads(cluster["summary_json"] or "{}")
    title = html.escape(summary.get("title") or cluster["title"])
    why = html.escape(summary.get("why_it_matters") or "Relevant to your configured watchlist.")
    bullets = summary.get("bullets") or []
    tickers = json.loads(cluster["ticker_symbols_json"] or "[]")
    topics = json.loads(cluster["topic_slugs_json"] or "[]")
    source_lines = []
    for index, document in enumerate(documents[:3], start=1):
        source_url = html.escape(document["url"])
        source_lines.append(f"{index}. {source_url}")
    lines = [
        f"<b>{title}</b>",
    ]
    if source_lines:
        lines.extend(source_lines)
    lines.extend(
        [
            "",
            f"<b>Why it matters:</b> {why}",
            "",
        ]
    )
    for bullet in bullets[:3]:
        lines.append(f"- {html.escape(str(bullet))}")
    if tickers:
        lines.append("")
        lines.append(f"<b>Tickers:</b> {html.escape(', '.join(tickers))}")
    if topics:
        lines.append(f"<b>Topics:</b> {html.escape(', '.join(topics))}")
    text = "\n".join(lines)
    if tickers:
        text += FINANCIAL_FOOTER
    return text


def format_digest_message(
    title: str,
    url: str,
    overview: str,
    highlights: list[str] | None = None,
) -> str:
    lines = [f"<b>{html.escape(title)}</b>", html.escape(overview)]
    if highlights:
        lines.append("")
        for highlight in highlights[:5]:
            lines.append(f"• {html.escape(highlight)}")
    lines.append("")
    lines.append(f'<a href="{html.escape(url)}">Open digest</a>')
    return "\n".join(lines)
