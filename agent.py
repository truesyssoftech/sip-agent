"""
agent.py
The brain. Runs the chosen LLM with tool use in a loop until it produces a
final answer.

Supported providers (set via PROVIDER env var):
  ANTHROPIC   — uses the official Anthropic Python SDK
  OPENROUTER  — uses OpenRouter's OpenAI-compatible REST API via the
                openai Python SDK (pip install openai)

Per-provider API keys:
  ANTHROPIC_API_KEY
  OPENROUTER_API_KEY

Model is read from the MODEL env var (default: claude-haiku-4-5-20251001).
"""

import os
import json
import logging
from tools import TOOLS, dispatch
import db

log = logging.getLogger("sip-agent")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PROVIDER = os.getenv("PROVIDER", "ANTHROPIC").upper().strip()
MODEL = os.getenv("MODEL", "claude-haiku-4-5-20251001")
MAX_TOOL_ROUNDS = 15

SUPPORTED_PROVIDERS = {"ANTHROPIC", "OPENROUTER"}
if PROVIDER not in SUPPORTED_PROVIDERS:
    raise ValueError(
        f"Unknown PROVIDER={PROVIDER!r}. Must be one of: {', '.join(SUPPORTED_PROVIDERS)}"
    )

# ---------------------------------------------------------------------------
# System prompt (unchanged)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are "SIP Saathi", a friendly mutual-fund SIP planning assistant for Indian investors.

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
- When a chart or PDF is generated, tell the user it's attached — the API handles sending the file.

HOW TO TALK:
- Warm, simple, India-context language. Use ₹ and Indian number formatting (lakh/crore) in your replies.
- Keep replies tight and scannable. Lead with the answer, then the key numbers, then one next step.
- When you assume a return rate for a projection, state the assumption (e.g. "assuming 12% p.a.").

COMPLIANCE — THIS IS NON-NEGOTIABLE:
- You are an EDUCATIONAL tool, NOT a SEBI-registered investment adviser.
- You may show data, projections, and historical performance, and explain concepts and trade-offs.
- Do NOT give a personalised "buy this exact fund now" instruction. Present options and reasoning, and let the user decide.
- Past performance does not guarantee future returns — make this clear whenever you show returns or projections.
- End substantive recommendations with a short reminder to consult a SEBI-registered adviser before investing.
"""

# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

def _run_anthropic(system: str, messages: list, tools: list) -> str:
    """
    Tool-use loop using the official Anthropic Python SDK.
    Returns the final assistant text reply.
    """
    from anthropic import Anthropic

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    # We pass user_id via closure — but dispatch needs it; handled in run_turn.
    # This function only manages the API loop; tool dispatch happens in run_turn.

    for _ in range(MAX_TOOL_ROUNDS):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system,
            tools=tools,
            messages=messages,
            cache_control={"type": "ephemeral"},
        )

        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            yield ("tool_use", resp.content)   # hand tool blocks back to caller
            continue

        # Final text
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        yield ("end", text)
        return

    yield ("end", "")


def _run_openrouter(system: str, messages: list, tools: list):
    """
    Tool-use loop using OpenRouter's OpenAI-compatible API via the openai SDK.
    Yields the same protocol as _run_anthropic: ("tool_use", blocks) | ("end", text)
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError(
            "openai package is required for OPENROUTER provider. "
            "Run: pip install openai"
        )

    client = OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    )

    # Convert Anthropic-style tool schemas → OpenAI function tool format
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]

    # Build OpenAI-style message list (system goes as first message)
    oai_messages = [{"role": "system", "content": system}] + [
        _anthropic_msg_to_openai(m) for m in messages
    ]

    for _ in range(MAX_TOOL_ROUNDS):
        resp = client.chat.completions.create(
            model=MODEL,
            max_tokens=1024,
            tools=openai_tools,
            messages=oai_messages,
        )

        choice = resp.choices[0]
        finish = choice.finish_reason
        msg = choice.message

        if finish == "tool_calls" and msg.tool_calls:
            # Append assistant turn
            oai_messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]})
            # Yield synthetic "blocks" that match what run_turn expects
            fake_blocks = [
                _OpenRouterToolBlock(tc.id, tc.function.name, json.loads(tc.function.arguments or "{}"))
                for tc in msg.tool_calls
            ]
            yield ("tool_use", fake_blocks, oai_messages)
            continue

        text = (msg.content or "").strip()
        yield ("end", text)
        return

    yield ("end", "")


# ---------------------------------------------------------------------------
# Tiny shim so OpenRouter tool blocks look like Anthropic tool_use blocks
# ---------------------------------------------------------------------------

class _OpenRouterToolBlock:
    def __init__(self, tool_use_id: str, name: str, input: dict):
        self.type = "tool_use"
        self.id = tool_use_id
        self.name = name
        self.input = input


# ---------------------------------------------------------------------------
# Message format converters
# ---------------------------------------------------------------------------

def _anthropic_msg_to_openai(m: dict) -> dict:
    """Convert a stored {role, content} message to OpenAI chat format."""
    role = m["role"]
    content = m["content"]

    # content may be a string (normal) or a list of blocks (tool results)
    if isinstance(content, str):
        return {"role": role, "content": content}

    if isinstance(content, list):
        # Tool result blocks from Anthropic format → OpenAI tool message(s)
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                parts.append({
                    "role": "tool",
                    "tool_call_id": block["tool_use_id"],
                    "content": block["content"],
                })
            else:
                # assistant blocks with text / tool_use — handled separately
                pass
        if parts:
            return parts  # will be flattened below
    return {"role": role, "content": str(content)}


def _flatten(msgs: list) -> list:
    """Flatten any nested lists produced by _anthropic_msg_to_openai."""
    out = []
    for m in msgs:
        if isinstance(m, list):
            out.extend(m)
        else:
            out.append(m)
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_turn(user_id: str, user_message: str) -> str:
    """
    Process one user message: load history + profile, run the tool loop,
    persist the assistant reply, and return the reply text.
    Works with both ANTHROPIC and OPENROUTER providers.
    """
    db.add_message(user_id, "user", user_message)

    profile = db.get_profile(user_id)
    history = db.get_recent_messages(user_id, limit=20)

    system = SYSTEM_PROMPT
    if profile:
        system += f"\n\nKNOWN USER PROFILE (from earlier): {profile}"

    messages = [{"role": m["role"], "content": m["content"]} for m in history]

    log.info("run_turn | provider=%s | model=%s | session=%s", PROVIDER, MODEL, user_id)

    if PROVIDER == "ANTHROPIC":
        reply = _run_turn_anthropic(system, messages, user_id)
    elif PROVIDER == "OPENROUTER":
        reply = _run_turn_openrouter(system, messages, user_id)
    else:
        reply = f"Unsupported provider: {PROVIDER}"

    db.add_message(user_id, "assistant", reply)
    return reply or "Sorry, I couldn't generate a reply. Please try rephrasing."


# ---------------------------------------------------------------------------
# Per-provider turn runners (handle tool dispatch + loop)
# ---------------------------------------------------------------------------

def _run_turn_anthropic(system: str, messages: list, user_id: str) -> str:
    from anthropic import Anthropic

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    for _ in range(MAX_TOOL_ROUNDS):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system,
            tools=TOOLS,
            messages=messages,
            cache_control={"type": "ephemeral"},
        )

        if resp.stop_reason == "tool_use":
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

        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        return text

    return "This is taking more steps than expected. Could you narrow the question a bit?"


def _run_turn_openrouter(system: str, messages: list, user_id: str) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError(
            "openai package is required for OPENROUTER provider. "
            "Run: pip install openai"
        )

    client = OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    )

    # Convert tool schemas to OpenAI function format
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in TOOLS
    ]

    # OpenAI-style message list with system as first message
    oai_messages = [{"role": "system", "content": system}] + [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if isinstance(m["content"], str)   # skip raw tool-result blocks
    ]

    for _ in range(MAX_TOOL_ROUNDS):
        resp = client.chat.completions.create(
            model=MODEL,
            max_tokens=1024,
            tools=openai_tools,
            messages=oai_messages,
        )

        choice = resp.choices[0]
        msg = choice.message

        if choice.finish_reason == "tool_calls" and msg.tool_calls:
            # Append assistant turn to context
            oai_messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })

            # Dispatch each tool call and append results
            for tc in msg.tool_calls:
                args = {}
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    pass
                result = dispatch(tc.function.name, args, user_id)
                oai_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            continue

        text = (msg.content or "").strip()
        return text

    return "This is taking more steps than expected. Could you narrow the question a bit?"
