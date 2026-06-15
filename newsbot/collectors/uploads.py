from __future__ import annotations

from pathlib import Path

import httpx

from newsbot.collectors.base import BaseCollector, CollectorResult
from newsbot.types import RawItem


class UploadsCollector(BaseCollector):
    async def collect(self, client: httpx.AsyncClient) -> CollectorResult:
        del client
        try:
            upload_dir = self.config.settings.upload_dir
            upload_dir.mkdir(parents=True, exist_ok=True)
            items: list[RawItem] = []
            for path in sorted(_iter_uploads(upload_dir)):
                stat = path.stat()
                items.append(
                    RawItem(
                        source_id=self.source.id,
                        external_id=f"{path.name}:{stat.st_mtime_ns}",
                        title=path.stem.replace("_", " ").replace("-", " ").strip() or path.name,
                        url=path.resolve().as_uri(),
                        published_at=None,
                        author="manual upload",
                        payload={
                            "connector": "uploads",
                            "local_path": str(path.resolve()),
                            "size_bytes": stat.st_size,
                        },
                    )
                )
            return CollectorResult(items=items)
        except Exception as exc:  # noqa: BLE001
            return self.failed(exc)


def _iter_uploads(path: Path) -> list[Path]:
    allowed = {".pdf", ".txt", ".md", ".html", ".htm"}
    return [item for item in path.iterdir() if item.is_file() and item.suffix.lower() in allowed]

