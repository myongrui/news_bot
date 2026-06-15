# Newsbot

Newsbot is a local-first Python app that collects public tech, AI, market, social, filing, and research signals, scores reliability and frontier importance, sends Telegram alerts, and publishes daily/weekly digest pages.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
newsbot web
```

Open `http://127.0.0.1:8000`.

Docker:

```powershell
docker compose up --build
```

## Required Secrets

Set these in `.env` for full operation:

- `OPENAI_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Optional:

- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`
- `X_BEARER_TOKEN`

Without OpenAI or Telegram credentials, the app can still ingest and render local digests using deterministic summaries, but production alerts should use the configured services.

## CLI

```powershell
newsbot ingest --source all
newsbot digest --period daily
newsbot digest --period weekly
newsbot alerts run
newsbot telegram test
newsbot telegram list --status pending --limit 10
newsbot curate preview --limit 20
newsbot curate rescore --limit 1000
newsbot web
```

## Frontier Policy

- Primary truth sources include SEC filings, company blogs, arXiv, official research pages, and official model/product posts.
- Fast-signal sources include Hacker News, Reddit, and optional X; they are treated as leads, not truth.
- Context sources include trusted media and broad news APIs.
- Independent/context sources now include CNBC, MarketWatch, MIT Technology Review, Ars Technica, WIRED AI, and VentureBeat AI so the feed is not only first-party company blogs.
- Policy and regulatory sources include SEC press releases and NIST news, with policy/regulation treated as a priority topic.
- Developer-tool sources include OpenAI Developers/Codex, GitHub, Cloudflare, Vercel, LangChain, Hugging Face, and cloud release feeds.
- Blue-chip market sources include SEC filings, public GDELT market coverage, public analyst-rating/price-target coverage, and Reddit investing discussions as social signals.
- Each story gets a frontier score from recency, source role, technical novelty, market impact, watchlist relevance, and corroboration.
- Telegram alerts require high reliability, frontier score at least `75`, age within `72` hours, and a priority topic or ticker.
- Telegram alerts are intentionally a little noisy: frontier score at least `68`, up to `5` queued per ingest run.
- Daily digests prioritize the top frontier stories, include a larger set of borderline items, and keep social-only items in a separate social-signal section.
- Web story cards include a `Not interesting` action; dismissed stories are hidden from normal digest/topic views.

## Reliability Policy

- Primary/official sources can trigger alerts when the frontier score is high enough.
- Community/social sources require independent corroboration before they trigger alerts.
- Social-only items are retained as digest signals and labeled as such.
- Analyst ratings and price targets are treated as market context, not recommendations.
- Stock-related content includes a not-financial-advice footer and avoids buy/sell recommendations.
- Crawlers use public APIs/feeds where possible and do not bypass paywalls.
