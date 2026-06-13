"""
tools.py
Defines the tools Claude can call (JSON schemas) and a dispatcher that runs them.
Tools = real fund data (mfapi.in) + financial math + web context + profile memory
      + chart generation + PDF plan generation.
"""
import json
import mf_data
import calculators as calc
import web_tools
import charts
import pdf_report
import db

# Files generated during a turn — bot.py reads and sends these after the agent reply.
_pending_files = []

def get_and_clear_pending_files():
    global _pending_files
    files = list(_pending_files)
    _pending_files = []
    return files

TOOLS = [
    {
        "name": "search_funds",
        "description": "Search Indian mutual fund schemes by name or keyword (e.g. 'Parag Parikh Flexi Cap', 'HDFC small cap', 'index fund'). Returns scheme codes you can use with get_fund_analysis. Always search before analysing a fund.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Fund name or keyword"}},
            "required": ["query"],
        },
    },
    {
        "name": "get_fund_analysis",
        "description": "Get a fund's category, fund house, latest NAV, and real trailing returns (1y/3y/5y CAGR and since-inception) computed from actual NAV history. Use this to evaluate or compare funds.",
        "input_schema": {
            "type": "object",
            "properties": {"scheme_code": {"type": "integer", "description": "AMFI scheme code from search_funds"}},
            "required": ["scheme_code"],
        },
    },
    {
        "name": "sip_backtest",
        "description": "Backtest a real monthly SIP into a specific fund using its actual NAV history. Returns total invested, current value, absolute return, and XIRR. Use when the user asks 'what if I had invested X/month in this fund'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "scheme_code": {"type": "integer"},
                "monthly": {"type": "number", "description": "Monthly SIP amount in rupees"},
                "years": {"type": "number", "description": "Backtest window in years"},
            },
            "required": ["scheme_code", "monthly", "years"],
        },
    },
    {
        "name": "calculate_sip",
        "description": "Project a flat monthly SIP's future value given an assumed annual return and tenure. Returns total invested, future value, and wealth gain.",
        "input_schema": {
            "type": "object",
            "properties": {
                "monthly": {"type": "number"},
                "annual_return_pct": {"type": "number", "description": "Assumed annual return, e.g. 12"},
                "years": {"type": "number"},
            },
            "required": ["monthly", "annual_return_pct", "years"],
        },
    },
    {
        "name": "calculate_stepup_sip",
        "description": "Project a step-up SIP where the monthly amount rises by a fixed percentage each year. Use when the user expects rising income.",
        "input_schema": {
            "type": "object",
            "properties": {
                "monthly": {"type": "number"},
                "annual_return_pct": {"type": "number"},
                "years": {"type": "integer"},
                "stepup_pct": {"type": "number", "description": "Yearly increase in SIP, e.g. 10"},
            },
            "required": ["monthly", "annual_return_pct", "years", "stepup_pct"],
        },
    },
    {
        "name": "goal_planner",
        "description": "Reverse SIP: compute the monthly investment needed to reach a target corpus in a given number of years at an assumed return. Use for goals like a house down payment or child's education.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_amount": {"type": "number"},
                "annual_return_pct": {"type": "number"},
                "years": {"type": "number"},
            },
            "required": ["target_amount", "annual_return_pct", "years"],
        },
    },
    {
        "name": "calculate_lumpsum",
        "description": "Project the future value of a one-time lumpsum investment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "amount": {"type": "number"},
                "annual_return_pct": {"type": "number"},
                "years": {"type": "number"},
            },
            "required": ["amount", "annual_return_pct", "years"],
        },
    },
    {
        "name": "web_search",
        "description": "Search the web for current market context: recent fund performance commentary, category trends, fund manager changes, or news. Use sparingly, only when current information genuinely helps.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "save_user_profile",
        "description": "Save what you learn about the user for future messages: their name, risk appetite (conservative/moderate/aggressive), monthly budget, goals, and time horizon. Call this whenever the user shares such details.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "risk": {"type": "string", "enum": ["conservative", "moderate", "aggressive"]},
                "monthly_budget": {"type": "number"},
                "goal": {"type": "string"},
                "horizon_years": {"type": "number"},
            },
        },
    },
    # ---- NEW: Charts & PDF ----
    {
        "name": "generate_nav_chart",
        "description": "Generate a NAV history chart for a fund (PNG image sent to user). Call AFTER get_fund_analysis when the user asks to see a fund's performance visually, or to enrich your reply.",
        "input_schema": {
            "type": "object",
            "properties": {
                "scheme_code": {"type": "integer"},
                "years": {"type": "number", "description": "How many years of history to plot (default 5)"},
            },
            "required": ["scheme_code"],
        },
    },
    {
        "name": "generate_projection_chart",
        "description": "Generate a SIP projection chart (invested vs growth over time, PNG). Use after calculate_sip or calculate_stepup_sip to visually show the user their wealth growth.",
        "input_schema": {
            "type": "object",
            "properties": {
                "monthly": {"type": "number"},
                "annual_return_pct": {"type": "number"},
                "years": {"type": "integer"},
                "stepup_pct": {"type": "number", "description": "0 for flat SIP"},
            },
            "required": ["monthly", "annual_return_pct", "years"],
        },
    },
    {
        "name": "generate_backtest_chart",
        "description": "Generate a backtest chart showing invested vs portfolio value over real NAV history (PNG). Call AFTER sip_backtest.",
        "input_schema": {
            "type": "object",
            "properties": {
                "scheme_code": {"type": "integer"},
                "monthly": {"type": "number"},
                "years": {"type": "number"},
            },
            "required": ["scheme_code", "monthly", "years"],
        },
    },
    {
        "name": "generate_plan_pdf",
        "description": "Generate a one-page PDF investment plan for the user — includes their profile, SIP projections (flat & step-up), fund analysis, backtest results, and charts. Call this when the user asks for a plan, a report, or a PDF, or when you have enough data to produce a summary doc. Pass in the data you already have from prior tool calls.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sip_projection": {
                    "type": "object",
                    "description": "Result from calculate_sip",
                },
                "stepup_projection": {
                    "type": "object",
                    "description": "Result from calculate_stepup_sip",
                },
                "goal_plan": {
                    "type": "object",
                    "description": "Result from goal_planner",
                },
                "fund_analyses": {
                    "type": "array",
                    "description": "List of results from get_fund_analysis",
                    "items": {"type": "object"},
                },
                "backtest": {
                    "type": "object",
                    "description": "Result from sip_backtest",
                },
            },
        },
    },
]


def dispatch(name: str, args: dict, user_id: str) -> str:
    """Execute a tool call and return a JSON string for Claude's tool_result."""
    global _pending_files
    try:
        if name == "search_funds":
            out = mf_data.search_funds(args["query"])

        elif name == "get_fund_analysis":
            fund = mf_data.get_fund(args["scheme_code"])
            if "error" in fund:
                out = fund
            else:
                meta = fund.get("meta", {})
                out = {
                    "scheme_name": meta.get("scheme_name"),
                    "fund_house": meta.get("fund_house"),
                    "category": meta.get("scheme_category"),
                    "returns": calc.trailing_returns(fund.get("data", [])),
                }

        elif name == "sip_backtest":
            fund = mf_data.get_fund(args["scheme_code"])
            if "error" in fund:
                out = fund
            else:
                out = calc.sip_backtest(fund.get("data", []), args["monthly"], args["years"])
                out["scheme_name"] = fund.get("meta", {}).get("scheme_name")

        elif name == "calculate_sip":
            out = calc.sip_future_value(args["monthly"], args["annual_return_pct"], args["years"])

        elif name == "calculate_stepup_sip":
            out = calc.stepup_sip_future_value(args["monthly"], args["annual_return_pct"],
                                               args["years"], args["stepup_pct"])

        elif name == "goal_planner":
            out = calc.required_sip_for_goal(args["target_amount"], args["annual_return_pct"], args["years"])

        elif name == "calculate_lumpsum":
            out = calc.lumpsum_future_value(args["amount"], args["annual_return_pct"], args["years"])

        elif name == "web_search":
            out = web_tools.web_search(args["query"])

        elif name == "save_user_profile":
            out = {"saved": db.save_profile(user_id, **args)}

        # ---- Charts ----
        elif name == "generate_nav_chart":
            fund = mf_data.get_fund(args["scheme_code"])
            if "error" in fund:
                out = fund
            else:
                scheme_name = fund.get("meta", {}).get("scheme_name", "Fund")
                yrs = args.get("years", 5)
                path = charts.nav_history_chart(fund["data"], scheme_name, yrs)
                if path:
                    _pending_files.append({"type": "photo", "path": path})
                    out = {"chart_generated": True, "message": "NAV history chart will be sent to the user."}
                else:
                    out = {"error": "Not enough data to generate chart."}

        elif name == "generate_projection_chart":
            stepup = args.get("stepup_pct", 0)
            path = charts.sip_projection_chart(
                args["monthly"], args["annual_return_pct"], args["years"], stepup
            )
            if path:
                _pending_files.append({"type": "photo", "path": path})
                out = {"chart_generated": True, "message": "Projection chart will be sent to the user."}
            else:
                out = {"error": "Could not generate projection chart."}

        elif name == "generate_backtest_chart":
            fund = mf_data.get_fund(args["scheme_code"])
            if "error" in fund:
                out = fund
            else:
                scheme_name = fund.get("meta", {}).get("scheme_name", "Fund")
                path = charts.sip_backtest_chart(
                    fund["data"], args["monthly"], args["years"], scheme_name
                )
                if path:
                    _pending_files.append({"type": "photo", "path": path})
                    out = {"chart_generated": True, "message": "Backtest chart will be sent to the user."}
                else:
                    out = {"error": "Not enough data to generate backtest chart."}

        # ---- PDF ----
        elif name == "generate_plan_pdf":
            profile = db.get_profile(user_id) or {}
            chart_paths = [f["path"] for f in _pending_files if f["type"] == "photo"]
            path = pdf_report.generate_plan_pdf(
                user_profile=profile,
                sip_projection=args.get("sip_projection"),
                stepup_projection=args.get("stepup_projection"),
                goal_plan=args.get("goal_plan"),
                fund_analyses=args.get("fund_analyses"),
                backtest=args.get("backtest"),
                chart_paths=chart_paths,
            )
            _pending_files.append({"type": "document", "path": path})
            out = {"pdf_generated": True, "message": "Your SIP plan PDF will be sent."}

        else:
            out = {"error": f"Unknown tool: {name}"}
    except Exception as e:
        out = {"error": f"Tool {name} crashed: {e}"}

    return json.dumps(out, ensure_ascii=False)
