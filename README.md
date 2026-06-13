# SIP Saathi — Mutual Fund SIP Advisor Agent (Telegram)

An AI agent that helps Indian investors plan SIPs, set goals, and analyse funds using
**real NAV data** + **real financial math** + **Claude** as the brain. Runs locally.

> Educational tool only. Not SEBI-registered investment advice. Past performance does
> not guarantee future returns.

---

## What it does

- **Plan a goal** — "₹50 lakh in 10 years" → required monthly SIP
- **Project a SIP** — flat or step-up, with future value and wealth gain
- **Analyse a fund** — real 1Y/3Y/5Y CAGR computed from actual NAV history
- **Backtest** — "what if I'd put ₹5,000/month in this fund for 5 years?" → invested, current value, **XIRR**
- **Remembers you** — risk profile, budget, goals persist across messages

## Architecture

```
Telegram (bot.py)
      │  user message
      ▼
agent.py  ── Claude (tool use, loop) ──┐
      │                                │ decides which tool
      ▼                                ▼
db.py (SQLite)              tools.py (dispatcher)
 profile + history            ├── mf_data.py     → mfapi.in (free, no key): search + NAV history
                              ├── calculators.py → SIP / step-up / goal / lumpsum / CAGR / XIRR backtest
                              └── web_tools.py   → Tavily search + Firecrawl fetch (optional)
```

**Data source:** [mfapi.in](https://www.mfapi.in) — free, no auth, 14k+ Indian schemes, daily NAV.
All returns and backtests are computed from real NAV history; nothing is hallucinated.

## Setup (local)

```bash
cd sip_agent
python3 -m venv .venv && source .venv/bin/activate   # optional
pip install -r requirements.txt

cp .env.example .env        # then fill in your keys
```

Get your keys:
- **ANTHROPIC_API_KEY** — console.anthropic.com
- **TELEGRAM_BOT_TOKEN** — message [@BotFather](https://t.me/BotFather) → `/newbot`
- TAVILY_API_KEY / FIRECRAWL_API_KEY — optional (live market context). Agent works without them.

## Run

```bash
python3 bot.py
```

Then open Telegram, find your bot, and send `/start`.

Commands: `/start` (intro) · `/reset` (wipe your profile + history).

## Test

```bash
python3 tests/test_logic.py
```

Validates the financial engine (SIP, goal round-trip, step-up, lumpsum, NAV parsing on
the real mfapi.in format, trailing CAGR, and XIRR backtest) against known-good values.

## Files

| File | Role |
|---|---|
| `bot.py` | Telegram front-end |
| `agent.py` | Claude tool-use loop + system prompt (incl. compliance framing) |
| `tools.py` | Tool schemas + dispatcher |
| `mf_data.py` | mfapi.in client (search, NAV history) with caching |
| `calculators.py` | All financial math (no network, fully tested) |
| `web_tools.py` | Tavily / Firecrawl wrappers (optional) |
| `db.py` | SQLite profile + history |
| `tests/test_logic.py` | Engine tests |

## Notes / next steps

- Default model is `claude-sonnet-4-6` (fast + cheap for chat). Override via `CLAUDE_MODEL`.
- Charts are auto-generated at 180 DPI (clean on mobile) and sent as Telegram photos.
- The PDF embeds any charts generated in the same turn for a complete one-page plan.
- Temporary chart/PDF files accumulate in `tmp_charts/` and `tmp_pdfs/` — add a cron or startup cleanup if needed.
- Possible add-ons: a 5-question risk quiz, voice-note input, multi-language support.
