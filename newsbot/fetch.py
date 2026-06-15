from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from newsbot.config import AppConfig
from newsbot.types import Document
from newsbot.utils import canonicalize_url, clean_text, snippet, stable_id, strip_html, utc_now


class RobotsCache:
    def __init__(self) -> None:
        self._cache: dict[str, RobotFileParser] = {}

    async def allowed(self, client: httpx.AsyncClient, url: str, user_agent: str) -> bool:
        split = urlsplit(url)
        if split.scheme not in {"http", "https"} or not split.netloc:
            return True
        origin = f"{split.scheme}://{split.netloc}"
        parser = self._cache.get(origin)
        if parser is None:
            parser = RobotFileParser()
            parser.set_url(f"{origin}/robots.txt")
            try:
                response = await client.get(f"{origin}/robots.txt", timeout=8)
                if response.status_code < 400:
                    parser.parse(response.text.splitlines())
                else:
                    parser.parse([])
            except httpx.HTTPError:
                parser.parse([])
            self._cache[origin] = parser
        return parser.can_fetch(user_agent, url)


class DocumentExtractor:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.robots = RobotsCache()

    async def extract_row(self, client: httpx.AsyncClient, row: object) -> Document | None:
        payload = json.loads(row["payload_json"] or "{}")
        local_path = payload.get("local_path")
        if local_path:
            text = self._extract_local(Path(local_path))
        elif row["content"]:
            text = strip_html(row["content"])
        else:
            text = await self._fetch_article_text(client, row["url"])
        if not text:
            return None
        document_id = stable_id("document", row["id"], canonicalize_url(row["url"]))
        return Document(
            id=document_id,
            raw_item_id=row["id"],
            source_id=row["source_id"],
            title=row["title"],
            url=row["url"],
            text=text,
            snippet=snippet(text),
            published_at=row["published_at"],
            author=row["author"],
            metadata={**payload, "extracted_at": utc_now()},
        )

    async def _fetch_article_text(self, client: httpx.AsyncClient, url: str) -> str | None:
        user_agent = self.config.settings.http_user_agent
        if not await self.robots.allowed(client, url, user_agent):
            return None
        response = await client.get(url, headers={"User-Agent": user_agent}, follow_redirects=True)
        if response.status_code >= 400:
            return None
        content_type = response.headers.get("content-type", "").lower()
        if "pdf" in content_type or urlsplit(str(response.url)).path.lower().endswith(".pdf"):
            return self._extract_pdf_bytes(response.content)
        html = response.text
        try:
            import trafilatura

            extracted = trafilatura.extract(
                html,
                url=str(response.url),
                include_comments=False,
                include_tables=False,
                favor_precision=True,
            )
            if extracted:
                return clean_text(extracted)
        except Exception:  # noqa: BLE001
            pass
        return strip_html(html)

    def _extract_local(self, path: Path) -> str | None:
        if not path.exists() or not path.is_file():
            return None
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._extract_pdf_bytes(path.read_bytes())
        if suffix in {".html", ".htm"}:
            return strip_html(path.read_text(encoding="utf-8", errors="ignore"))
        return clean_text(path.read_text(encoding="utf-8", errors="ignore"))

    def _extract_pdf_bytes(self, content: bytes) -> str | None:
        try:
            import fitz

            with fitz.open(stream=content, filetype="pdf") as pdf:
                text = "\n".join(page.get_text("text") for page in pdf)
            return clean_text(text)
        except Exception:  # noqa: BLE001
            return None
