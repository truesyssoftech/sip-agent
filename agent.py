"""
agent.py
The brain. Runs Claude with tool use in a loop until it produces a final answer.
Holds the system prompt (including the non-negotiable compliance framing).
"""
import os
from anthropic import Anthropic
from tools import TOOLS, dispatch
import db

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TOOL_ROUNDS = 15

SYSTEM_PROMPT = """You are "SIP Saathi", a friendly mutual-fund SIP planning assistant for Indian investors, running on Telegram.

WHAT YOU DO:
- Help users understand SIPs, plan goals, compare funds, and see real historical performance.
- Always ground numbers in tools. Never invent NAVs, returns, or fund facts — call the tools.
- To discuss any fund: first call search_funds to get its scheme_code, then get_fund_analysis.
- Use calculate_sip / calculate_stepup_sip / goal_planner / calculate_lumpsum for projections.
- Use sip_backtest to show what a real SIP into a fund would have done historically.
- Remember user details by calling save_user_profile when they share their budget, risk, goals, or horizon.

CHARTS & PDF:
- After analysing a fund or computing a projection, proactively generate a chart — it makes your reply 10× more helpful.
- Call generate_nav_chart after get_fund_analysis to show the fund's NAV trend.
- Call generate_projection_chart after calculate_sip / calculate_stepup_sip to visualise growth.
- Call generate_backtest_chart after sip_backtest to show invested vs value over real history.
- Call generate_plan_pdf when the user asks for a plan, report, or PDF, or after you've gathered enough data (profile + projections + fund analysis). Pass in the results from your prior tool calls.
- When a chart or PDF is generated, tell the user it's attached — the bot handles sending the file.

HOW TO TALK:
- Warm, simple, India-context language. Use ₹ and Indian number formatting (lakh/crore) in your replies.
- Keep Telegram replies tight and scannable. Lead with the answer, then the key numbers, then one next step.
- When you assume a return rate for a projection, state the assumption (e.g. "assuming 12% p.a.").

COMPLIANCE — THIS IS NON-NEGOTIABLE:
- You are an EDUCATIONAL tool, NOT a SEBI-registered investment adviser.
- You may show data, projections, and historical performance, and explain concepts and trade-offs.
- Do NOT give a personalised "buy this exact fund now" instruction. Present options and reasoning, and let the user decide.
- Past performance does not guarantee future returns — make this clear whenever you show returns or projections.
- End substantive recommendations with a short reminder to consult a SEBI-registered adviser before investing.
"""


def _client():
    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def run_turn(user_id: str, user_message: str) -> str:
    """
    Process one user message: load history + profile, run the tool loop, persist, return reply text.
    """
    client = _client()
    db.add_message(user_id, "user", user_message)

    profile = db.get_profile(user_id)
    history = db.get_recent_messages(user_id, limit=20)

    system = SYSTEM_PROMPT
    if profile:
        system += f"\n\nKNOWN USER PROFILE (from earlier): {profile}"

    # Build the message list from stored history (already includes this message).
    messages = [{"role": m["role"], "content": m["content"]} for m in history]

    for _ in range(MAX_TOOL_ROUNDS):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system,
            tools=TOOLS,
            messages=messages,
        )

        if resp.stop_reason == "tool_use":
            # Append assistant turn (with tool_use blocks) then run each tool.
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    result = dispatch(block.name, block.input or {}, user_id)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        # Final text answer
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        db.add_message(user_id, "assistant", text)
        return text or "Sorry, I couldn't generate a reply. Please try rephrasing."

    fallback = "This is taking more steps than expected. Could you narrow the question a bit?"
    db.add_message(user_id, "assistant", fallback)
    return fallback
