from __future__ import annotations

import argparse
import asyncio
import json
import sys

from newsbot.config import load_app_config
from newsbot.curation import CurationPolicy
from newsbot.digest import DigestBuilder
from newsbot.db import Database
from newsbot.frontier import FrontierScorer, source_role
from newsbot.pipeline import NewsPipeline
from newsbot.telegram import TelegramClient


def safe_print(value: object = "") -> None:
    text = str(value)
    try:
        print(text)
    except UnicodeEncodeError:
        encoded = text.encode(sys.stdout.encoding or "utf-8", errors="replace")
        print(encoded.decode(sys.stdout.encoding or "utf-8", errors="replace"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="newsbot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest")
    ingest.add_argument(
        "--source",
        default="all",
        choices=["all", "rss", "hn", "arxiv", "sec", "gdelt", "reddit", "uploads", "x"],
    )

    digest = subparsers.add_parser("digest")
    digest.add_argument("--period", choices=["daily", "weekly"], required=True)

    alerts = subparsers.add_parser("alerts")
    alerts_sub = alerts.add_subparsers(dest="alerts_command", required=True)
    alerts_sub.add_parser("run")

    telegram = subparsers.add_parser("telegram")
    telegram_sub = telegram.add_subparsers(dest="telegram_command", required=True)
    telegram_sub.add_parser("test")
    telegram_list = telegram_sub.add_parser("list")
    telegram_list.add_argument("--status", choices=["pending", "sent", "failed"])
    telegram_list.add_argument("--limit", type=int, default=10)
    telegram_clear = telegram_sub.add_parser("clear")
    telegram_clear.add_argument("--status", choices=["pending", "sent", "failed"], default="pending")

    web = subparsers.add_parser("web")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8000)
    web.add_argument("--no-scheduler", action="store_true")

    curate = subparsers.add_parser("curate")
    curate_sub = curate.add_subparsers(dest="curate_command", required=True)
    preview = curate_sub.add_parser("preview")
    preview.add_argument("--limit", type=int, default=20)
    rescore = curate_sub.add_parser("rescore")
    rescore.add_argument("--limit", type=int, default=1000)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "ingest":
        report = asyncio.run(NewsPipeline().ingest(args.source))
        safe_print(
            "Ingest complete: "
            f"collected={report.collected} extracted={report.extracted} "
            f"clustered={report.clustered} alerts_queued={report.alerts_queued}"
        )
        return
    if args.command == "digest":
        digest_id = asyncio.run(DigestBuilder().build(args.period))
        safe_print(f"Digest saved: {digest_id}")
        return
    if args.command == "alerts" and args.alerts_command == "run":
        sent, failed = asyncio.run(NewsPipeline().run_alerts())
        safe_print(f"Alerts processed: sent={sent} failed={failed}")
        return
    if args.command == "telegram" and args.telegram_command == "test":
        config = load_app_config()
        telegram = TelegramClient(config.settings.telegram_bot_token, config.settings.telegram_chat_id)
        asyncio.run(telegram.send_message("<b>Newsbot test</b>\nTelegram is configured."))
        safe_print("Telegram test sent")
        return
    if args.command == "telegram" and args.telegram_command == "list":
        config = load_app_config()
        db = Database(config.settings.sqlite_path)
        db.init()
        rows = db.list_telegram_messages(status=args.status, limit=args.limit)
        if not rows:
            safe_print("No Telegram messages found.")
            return
        for row in rows:
            safe_print(f"--- {row['created_at']} | {row['status']} | id={row['id']}")
            if row["error"]:
                safe_print(f"error: {row['error']}")
            safe_print(row["text"])
        return
    if args.command == "telegram" and args.telegram_command == "clear":
        config = load_app_config()
        db = Database(config.settings.sqlite_path)
        db.init()
        deleted = db.delete_telegram_messages(status=args.status)
        safe_print(f"Deleted {deleted} Telegram messages with status={args.status}")
        return
    if args.command == "web":
        import uvicorn
        from newsbot.web import create_app

        app = create_app(start_scheduler=not args.no_scheduler)
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            reload=False,
            log_level="info",
        )
        return
    if args.command == "curate" and args.curate_command == "preview":
        config = load_app_config()
        db = Database(config.settings.sqlite_path)
        db.init()
        policy = CurationPolicy(config.curation)
        rows = sorted(db.list_clusters(limit=max(args.limit * 3, 50)), key=policy.sort_key, reverse=True)
        for index, row in enumerate(rows[: args.limit], start=1):
            summary = json.loads(row["summary_json"] or "{}")
            title = summary.get("title") or row["title"]
            topics = ", ".join(json.loads(row["topic_slugs_json"] or "[]")) or "-"
            tickers = ", ".join(json.loads(row["ticker_symbols_json"] or "[]")) or "-"
            reasons = ", ".join(json.loads(row["frontier_reasons_json"] or "[]")[:4]) or "-"
            safe_print(
                f"{index:02d}. frontier={int(row['frontier_score'] or 0)} "
                f"reliability={row['reliability_score']:.2f} "
                f"category={row['frontier_category']} topics={topics} tickers={tickers} "
                f"reasons={reasons} :: {title}"
            )
        return
    if args.command == "curate" and args.curate_command == "rescore":
        config = load_app_config()
        db = Database(config.settings.sqlite_path)
        db.init()
        scorer = FrontierScorer()
        rows = db.list_clusters(limit=args.limit)
        rescored = 0
        for row in rows:
            documents = db.cluster_documents(row["id"])
            if not documents:
                continue
            first = documents[0]
            source_roles = [
                source_role(config.source_by_id(document["source_id"]))
                for document in documents
            ]
            result = scorer.score(
                text=f"{row['title']} {first['snippet']} {first['text'][:2000]}",
                published_at=first["published_at"],
                source_roles=source_roles,
                topics=json.loads(row["topic_slugs_json"] or "[]"),
                tickers=json.loads(row["ticker_symbols_json"] or "[]"),
                social_only=bool(row["is_social_signal"]),
                source_count=len(documents),
            )
            db.update_cluster_frontier(
                row["id"],
                frontier_score=result.score,
                frontier_category=result.category,
                frontier_reasons=result.reasons,
            )
            rescored += 1
        safe_print(f"Rescored {rescored} clusters")
        return
    parser.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
