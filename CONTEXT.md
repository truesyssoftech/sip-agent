# SIP Saathi — Project Context

> **Purpose of this file:** Comprehensive technical context for AI-assisted development. Read this before making any changes to the project.

---

## Project Overview

**SIP Saathi** is a Telegram chatbot that acts as an AI-powered mutual fund SIP planning assistant for Indian investors. It uses **Claude (Anthropic)** as the AI brain with tool-use (function calling) to perform real financial calculations and fetch live fund data.

- **Language:** Python 3
- **AI Model:** `claude-sonnet-4-6` (default, overridable via `CLAUDE_MODEL` env var)
- **Interface:** Telegram Bot (via `python-telegram-bot` v21+)
- **Data Source:** [mfapi.in](https://www.mfapi.in) — free, no auth, 14k+ Indian mutual fund schemes
- **Database:** SQLite (`sip_agent.db`) — local, file-based
- **Run command:** `python bot.py`
- **Test command:** `python tests/test_logic.py`

---

## Architecture

```
User (Telegram)
    │
    ▼
bot.py  ←──────────────────────────────────────────────────────┐
  │  (async, handles commands + messages, sends files)          │
  │                                                             │
  ▼                                                             │
agent.py  ←── Claude API (tool_use loop, max 15 rounds)        │
  │  run_turn(user_id, message) → reply str                     │
  │                                                             │
  ├── db.py (SQLite)                                            │
  │     • profiles table: user risk, goals, budget, horizon     │
  │     • history table: rolling 20-message conversation window │
  │                                                             │
  └── tools.py (TOOLS schema + dispatch())                      │
        ├── mf_data.py  → mfapi.in REST API (1h in-memory cache)│
        ├── calculators.py → pure financial math (no network)   │
        ├── web_tools.py → Tavily search + Firecrawl (optional) │
        ├── charts.py → matplotlib PNG generation               │
        └── pdf_report.py → ReportLab PDF generation            │
              (files queued in _pending_files[] → sent by bot.py)┘
```

---

## File-by-File Reference

### `bot.py` — Telegram Front-End
- Entry point: `main()` calls `db.init_db()`, sets up `Application` with polling
- **Commands:** `/start` (welcome msg), `/reset` (wipe profile + history)
- **Message handler:** `handle_message()` — calls `agent.run_turn()` in a thread (`asyncio.to_thread`)
- After agent reply, reads `get_and_clear_pending_files()` and sends charts as photos, PDFs as documents
- Telegram message limit: 4096 chars → splits reply into 4000-char chunks
- Timeouts: connect=20s, read=30s, write=30s

### `agent.py` — Claude Tool-Use Loop
- `run_turn(user_id, message)` → loads history + profile from DB, runs Claude tool loop, returns text
- `MAX_TOOL_ROUNDS = 15` — max tool iterations per turn
- `MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")`
- `max_tokens = 1024` per Claude call
- Uses `cache_control={"type": "ephemeral"}` on messages
- System prompt is **`SYSTEM_PROMPT`** constant (includes compliance framing)
- Profile is appended to system prompt as `KNOWN USER PROFILE (from earlier): {profile}`
- History: last 20 messages from DB

**System Prompt Key Rules (DO NOT change without care):**
1. Always call `search_funds` first, then `get_fund_analysis` — never invent NAVs
2. Generate charts proactively after analyses/projections
3. Use ₹ and Indian number format (lakh/crore)
4. COMPLIANCE: Educational only, not SEBI-registered advice
5. End recommendations with a SEBI disclaimer

### `tools.py` — Tool Schemas + Dispatcher
- `TOOLS` list: Claude-compatible JSON schemas for all 13 tools
- `_pending_files` module-level list: accumulates `{"type": "photo"|"document", "path": str}` during a turn
- `get_and_clear_pending_files()`: consumed by `bot.py` after agent turn
- `dispatch(name, args, user_id)`: routes tool calls, always returns `json.dumps(result)`

**Available Tools:**

| Tool | Purpose | Key Inputs |
|---|---|---|
| `search_funds` | Search MF schemes by name | `query` |
| `get_fund_analysis` | Real NAV-based CAGR + meta | `scheme_code` |
| `sip_backtest` | Historical SIP simulation + XIRR | `scheme_code, monthly, years` |
| `calculate_sip` | Flat SIP future value | `monthly, annual_return_pct, years` |
| `calculate_stepup_sip` | Step-up SIP future value | `monthly, annual_return_pct, years, stepup_pct` |
| `goal_planner` | Required monthly SIP for a target | `target_amount, annual_return_pct, years` |
| `calculate_lumpsum` | One-time investment future value | `amount, annual_return_pct, years` |
| `web_search` | Tavily web search (optional) | `query` |
| `save_user_profile` | Persist user profile to DB | `name, risk, monthly_budget, goal, horizon_years` |
| `generate_nav_chart` | PNG chart of NAV history | `scheme_code, years?` |
| `generate_projection_chart` | PNG chart of SIP growth | `monthly, annual_return_pct, years, stepup_pct?` |
| `generate_backtest_chart` | PNG chart of backtest invested vs value | `scheme_code, monthly, years` |
| `generate_plan_pdf` | Full PDF investment plan | `sip_projection?, stepup_projection?, goal_plan?, fund_analyses?, backtest?` |

### `mf_data.py` — mfapi.in Client
- `BASE = "https://api.mfapi.in"`
- In-memory cache `_cache` with 1-hour TTL (`_CACHE_TTL = 3600`)
- `search_funds(query, limit=8)`: sorts results preferring Direct + Growth plans over IDCW/Dividend
- `get_fund(scheme_code)`: returns `{meta: {...}, data: [{date, nav}, ...]}` — data is **newest-first**
- `get_latest_nav(scheme_code)`: lightweight latest NAV only
- All HTTP calls use `User-Agent: sip-advisor-agent/1.0`, timeout=15s

### `calculators.py` — Pure Financial Math
All functions are **pure** (no network, no side effects). All amounts are plain floats; rates are annual percentages.

| Function | Formula / Note |
|---|---|
| `sip_future_value(monthly, annual_pct, years)` | Standard SIP FV, contributions at start of month: `P * [((1+i)^n-1)/i] * (1+i)` |
| `stepup_sip_future_value(monthly, annual_pct, years, stepup_pct)` | Year-by-year, monthly increases by `stepup_pct` at year start |
| `required_sip_for_goal(target, annual_pct, years)` | Reverse SIP: `P = FV * i / (((1+i)^n - 1) * (1+i))` |
| `lumpsum_future_value(amount, annual_pct, years)` | `FV = amount * (1 + r/100)^years` |
| `trailing_returns(nav_data)` | CAGR for 1Y/3Y/5Y + since-inception from real NAV; expects newest-first list |
| `sip_backtest(nav_data, monthly, years)` | Buys units on first NAV on/after monthly anchor; reports invested, value, XIRR |
| `_xirr(cashflows)` | XIRR via bisection (no scipy); outflows negative, final inflow positive |
| `_parse_nav_series(nav_data)` | Converts `{date: DD-MM-YYYY, nav: str}` → sorted oldest-first `[(datetime, float)]`, skips zeros/bad |

### `db.py` — SQLite Persistence
- DB path: `sip_agent.db` in project root (override via `DB_PATH` env var)
- **Tables:**
  - `profiles(user_id PK, name, risk, profile_json TEXT, updated_at)` — full profile in JSON
  - `history(id, user_id, role, content, created_at)` — chat messages
- `save_profile(user_id, **fields)`: merges new fields into existing profile JSON (partial updates safe)
- `get_recent_messages(user_id, limit=20)`: returns oldest-first list of `{role, content}`
- `clear_user(user_id)`: deletes both history and profile (used by `/reset`)

### `charts.py` — PNG Chart Generation
- Output dir: `tmp_charts/` — files accumulate (no auto-cleanup)
- Resolution: 180 DPI (clean on mobile)
- Filename pattern: `sip_{uuid8}.png`
- **Color palette:**
  - Primary: `#6366f1` (indigo)
  - Secondary: `#22d3ee` (cyan)
  - Invested: `#94a3b8` (slate)
  - Gain: `#34d399` (emerald)
  - BG: `#ffffff`, Text: `#1e293b`, Grid: `#e2e8f0`
- **Three chart types:**
  1. `nav_history_chart(nav_data, scheme_name, years=5)` — filled area NAV line
  2. `sip_projection_chart(monthly, annual_pct, years, stepup_pct=0)` — invested vs gains area
  3. `sip_backtest_chart(nav_data, monthly, years, scheme_name)` — real backtest invested vs value
- Returns `None` if insufficient data (< 20 rows for NAV chart, < 12 for backtest)

### `pdf_report.py` — PDF Plan Generation
- Output dir: `tmp_pdfs/` — files accumulate (no auto-cleanup)
- Filename pattern: `sip_plan_{uuid8}.pdf`
- Uses **ReportLab Platypus** (`SimpleDocTemplate`, `Table`, `Image`, `Paragraph`)
- Page size: A4, margins: left/right 18mm, top 15mm, bottom 12mm
- **Color scheme:** Indigo `#6366f1`, Dark `#1e293b`, Slate `#64748b`, Light `#f1f5f9`
- `generate_plan_pdf(user_profile, sip_projection, stepup_projection, goal_plan, fund_analyses, backtest, chart_paths)` — all args optional
- Sections: Header → Profile → SIP Projections Table → Goal Planner → Fund Analysis Table → Backtest → Charts → Disclaimer
- Up to 4 fund analyses shown in the table

### `web_tools.py` — Optional Web Context
- `web_search(query, max_results=5)` — Tavily API; returns `{answer, results[{title, url, content}]}`
- `fetch_page(url)` — Firecrawl API; returns `{url, content}` (markdown, max 4000 chars)
- Both gracefully return `{"error": "..."}` if API keys are absent

### `tests/test_logic.py`
- Standalone test script; adds project root to `sys.path`
- Tests: `sip_future_value`, goal round-trip, step-up vs flat, lumpsum, NAV parsing, trailing CAGR (on 6yr synthetic 10% series), XIRR backtest
- Run with: `python tests/test_logic.py`; exits 0 on all pass, 1 if any fail

---

## Environment Variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ Yes | — | Claude API access |
| `TELEGRAM_BOT_TOKEN` | ✅ Yes | — | Telegram bot |
| `CLAUDE_MODEL` | No | `claude-sonnet-4-6` | Override AI model |
| `TAVILY_API_KEY` | No | — | Web search (graceful fallback) |
| `FIRECRAWL_API_KEY` | No | — | Deep page fetch (graceful fallback) |
| `DB_PATH` | No | `./sip_agent.db` | Override SQLite path |

---

## Dependencies (`requirements.txt`)

```
anthropic>=0.40.0
python-telegram-bot>=21.0
requests>=2.31.0
python-dotenv>=1.0.0
matplotlib>=3.8.0
reportlab>=4.0.0
```

No `scipy` — XIRR is implemented from scratch via bisection in `calculators.py`.

---

## Key Design Patterns & Conventions

1. **Tool result format:** All `dispatch()` calls return `json.dumps(result, ensure_ascii=False)` — always a JSON string
2. **File queuing:** Charts/PDFs are queued in `_pending_files` (module-level global in `tools.py`), cleared by `bot.py` after each turn
3. **Error handling:** All tools return `{"error": "..."}` on failure — Claude handles these gracefully
4. **NAV data direction:** mfapi.in returns NAV data **newest-first**. `calculators.py` and `charts.py` both sort to oldest-first internally
5. **User profile:** Partial updates are safe — `save_profile` merges into existing JSON
6. **History limit:** Last 20 messages loaded per turn (hard-coded in `agent.py`)
7. **Caching:** mfapi.in responses cached in-memory for 1 hour per process
8. **Compliance:** System prompt compliance framing must be preserved — non-negotiable per comments in `agent.py`
9. **India formatting:** Use ₹ symbol and lakh/crore in all user-facing text; `_fmt_inr()` helpers exist in both `charts.py` and `pdf_report.py`
10. **Temp file cleanup:** `tmp_charts/` and `tmp_pdfs/` accumulate — suggest cron/startup cleanup for production

---

## Temporary Directories

| Directory | Contents | Cleanup |
|---|---|---|
| `tmp_charts/` | PNG files from `charts.py` | Manual / cron |
| `tmp_pdfs/` | PDF files from `pdf_report.py` | Manual / cron |
| `__pycache__/` | Python bytecode | Auto |

---

## Potential Improvements / Known TODOs (from README)

- Add a 5-question risk quiz on `/start`
- Voice-note input support
- Multi-language support (Hindi, Tamil, etc.)
- Startup/cron cleanup for `tmp_charts/` and `tmp_pdfs/`
- Add async/await support to `agent.run_turn` (currently runs in thread via `asyncio.to_thread`)
- Port to webhook mode for production deployment
- Rate limiting per user
- Persistent disk cache for mfapi.in (currently only in-memory, lost on restart)

---

## Common Development Tasks

### Add a New Tool
1. Add JSON schema to `TOOLS` list in `tools.py`
2. Add handler branch in `dispatch()` in `tools.py`
3. Add description to `SYSTEM_PROMPT` in `agent.py` (when/how to use the tool)
4. Implement the actual function in the appropriate module

### Change the AI Model
- Set `CLAUDE_MODEL` env var, e.g. `CLAUDE_MODEL=claude-opus-4`
- Or edit default in `agent.py` line 11

### Add a New Chart Type
1. Implement function in `charts.py` returning PNG path (or `None` on failure)
2. Add tool schema + dispatch in `tools.py`
3. Queue result via `_pending_files.append({"type": "photo", "path": path})`

### Run Locally
```bash
# Windows (PowerShell)
cd e:\WORKSPACE\SIPAGENT\sip-agent
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .sample .env    # fill in your keys
python bot.py
```

---

*Last updated: 2026-06-13*
