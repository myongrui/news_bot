from __future__ import annotations

import json
import re
import shutil
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from newsbot.config import load_app_config
from newsbot.db import Database
from newsbot.digest import _iso_week
from newsbot.scheduler import create_scheduler

PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))


def create_app(*, start_scheduler: bool = True) -> FastAPI:
    config = load_app_config()
    db = Database(config.settings.sqlite_path)
    db.init()
    db.upsert_sources(config.sources)
    scheduler = create_scheduler(config) if start_scheduler else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        del app
        if scheduler and not scheduler.running:
            scheduler.start()
        yield
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=False)

    app = FastAPI(title="Newsbot", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")

    @app.get("/")
    async def index(request: Request):
        digest = db.latest_digest("daily")
        clusters = db.list_clusters(limit=30)
        return templates.TemplateResponse(
            request,
            "day.html",
            _digest_context(db, digest, clusters, title="Latest Daily Brief"),
        )

    @app.get("/day/{day}")
    async def day(request: Request, day: str):
        _validate_day(day)
        digest = db.digest_by_start("daily", day)
        start = datetime.fromisoformat(day).replace(tzinfo=UTC)
        clusters = db.list_clusters(since=start.isoformat(), limit=50)
        return templates.TemplateResponse(
            request,
            "day.html",
            _digest_context(db, digest, clusters, title=f"Daily Brief {day}"),
        )

    @app.get("/week/{week_id}")
    async def week(request: Request, week_id: str):
        start = _week_start(week_id)
        digest = db.digest_by_start("weekly", start.date().isoformat())
        clusters = db.list_clusters(since=start.isoformat(), limit=80)
        return templates.TemplateResponse(
            request,
            "week.html",
            _digest_context(db, digest, clusters, title=f"Weekly Brief {week_id}"),
        )

    @app.get("/topic/{slug}")
    async def topic(request: Request, slug: str):
        clusters = [_cluster_view(db, row) for row in db.list_clusters(topic=slug, limit=100)]
        topic_name = next((topic.name for topic in config.topics if topic.slug == slug), slug)
        return templates.TemplateResponse(
            request,
            "topic.html",
            {
                "title": topic_name,
                "topic": {"slug": slug, "name": topic_name},
                "clusters": clusters,
                "counts": db.counts(),
                "current_week": _iso_week(datetime.now(UTC)),
            },
        )

    @app.get("/upload")
    async def upload_form(request: Request):
        uploads = sorted(config.settings.upload_dir.glob("*"))
        return templates.TemplateResponse(
            request,
            "upload.html",
            {
                "title": "Uploads",
                "uploads": [path for path in uploads if path.is_file()],
                "counts": db.counts(),
                "current_week": _iso_week(datetime.now(UTC)),
            },
        )

    @app.post("/upload")
    async def upload_file(file: UploadFile = File(...)):
        config.settings.upload_dir.mkdir(parents=True, exist_ok=True)
        filename = _safe_filename(file.filename or "upload.bin")
        destination = config.settings.upload_dir / filename
        with destination.open("wb") as handle:
            shutil.copyfileobj(file.file, handle)
        return RedirectResponse(url="/upload", status_code=303)

    @app.post("/feedback/{cluster_id}")
    async def feedback(
        request: Request,
        cluster_id: str,
        label: str = Form(...),
        next_url: str = Form(default="/"),
    ):
        if label == "clear":
            db.clear_cluster_feedback(cluster_id)
        else:
            db.set_cluster_feedback(cluster_id, label)
        redirect_to = next_url if next_url.startswith("/") else str(request.headers.get("referer") or "/")
        return RedirectResponse(url=redirect_to, status_code=303)

    @app.get("/health")
    async def health(request: Request):
        return templates.TemplateResponse(
            request,
            "health.html",
            {
                "title": "Health",
                "counts": db.counts(),
                "sources": db.health_rows(),
                "scheduler_running": bool(scheduler and scheduler.running),
                "current_week": _iso_week(datetime.now(UTC)),
                "settings": {
                    "database": str(config.settings.sqlite_path),
                    "timezone": config.settings.timezone,
                    "telegram_configured": bool(
                        config.settings.telegram_bot_token and config.settings.telegram_chat_id
                    ),
                    "openai_configured": bool(config.settings.openai_api_key),
                },
            },
        )

    return app


def _digest_context(db: Database, digest: Any, clusters: list[Any], *, title: str) -> dict[str, Any]:
    payload = json.loads(digest["payload_json"]) if digest else {}
    digest_payload = payload.get("digest", {})
    cluster_views = [_cluster_view(db, row) for row in clusters]
    return {
        "title": digest["title"] if digest else title,
        "digest": digest,
        "digest_payload": digest_payload,
        "clusters": cluster_views,
        "counts": db.counts(),
        "current_week": _iso_week(datetime.now(UTC)),
    }


def _cluster_view(db: Database, row: Any) -> dict[str, Any]:
    summary = json.loads(row["summary_json"] or "{}")
    return {
        "id": row["id"],
        "title": summary.get("title") or row["title"],
        "confidence": summary.get("confidence") or row["confidence"],
        "why_it_matters": summary.get("why_it_matters"),
        "bullets": summary.get("bullets", []),
        "topics": json.loads(row["topic_slugs_json"] or "[]"),
        "tickers": json.loads(row["ticker_symbols_json"] or "[]"),
        "score": row["reliability_score"],
        "frontier_score": row["frontier_score"],
        "frontier_category": row["frontier_category"],
        "frontier_reasons": json.loads(row["frontier_reasons_json"] or "[]"),
        "feedback": db.get_cluster_feedback(row["id"]),
        "is_social_signal": bool(row["is_social_signal"]),
        "documents": db.cluster_documents(row["id"])[:3],
    }


def _validate_day(value: str) -> None:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise HTTPException(status_code=404, detail="day must be YYYY-MM-DD")


def _week_start(value: str) -> datetime:
    match = re.fullmatch(r"(\d{4})-W(\d{2})", value)
    if not match:
        raise HTTPException(status_code=404, detail="week must be YYYY-Www")
    year = int(match.group(1))
    week = int(match.group(2))
    try:
        return datetime.fromisocalendar(year, week, 1).replace(tzinfo=UTC)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="invalid ISO week") from exc


def _safe_filename(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(value).name).strip("._")
    return stem or "upload.bin"
