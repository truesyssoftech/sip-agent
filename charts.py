"""
charts.py
Generates clean, visually appealing charts as PNG files.
Returns the file path — the bot sends it as a Telegram photo.
"""
import os
import uuid
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from datetime import datetime, timedelta
from typing import List, Dict, Optional

CHART_DIR = os.path.join(os.path.dirname(__file__), "tmp_charts")
os.makedirs(CHART_DIR, exist_ok=True)

# ---------- style ----------
COLORS = {
    "primary": "#6366f1",    # indigo
    "secondary": "#22d3ee",  # cyan
    "invested": "#94a3b8",   # slate
    "gain": "#34d399",       # emerald
    "bg": "#ffffff",
    "text": "#1e293b",
    "grid": "#e2e8f0",
}


def _fmt_inr(x, _=None):
    """Format a number as ₹ lakh/crore style."""
    if abs(x) >= 1e7:
        return f"₹{x/1e7:.1f}Cr"
    if abs(x) >= 1e5:
        return f"₹{x/1e5:.1f}L"
    if abs(x) >= 1e3:
        return f"₹{x/1e3:.0f}K"
    return f"₹{x:.0f}"


def _save(fig):
    path = os.path.join(CHART_DIR, f"sip_{uuid.uuid4().hex[:8]}.png")
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor=COLORS["bg"])
    plt.close(fig)
    return path


def _parse_nav(nav_data: List[Dict]):
    out = []
    for row in nav_data:
        try:
            d = datetime.strptime(row["date"], "%d-%m-%Y")
            v = float(row["nav"])
            if v > 0:
                out.append((d, v))
        except (ValueError, KeyError, TypeError):
            continue
    out.sort(key=lambda x: x[0])
    return out


# ---------- Chart 1: NAV history ----------

def nav_history_chart(nav_data: List[Dict], scheme_name: str, years: float = 5) -> str:
    """Plot the fund's NAV over the last `years`. Returns PNG path."""
    series = _parse_nav(nav_data)
    if len(series) < 20:
        return None

    cutoff = series[-1][0] - timedelta(days=int(365.25 * years))
    series = [(d, v) for d, v in series if d >= cutoff]
    dates = [d for d, _ in series]
    navs = [v for _, v in series]

    fig, ax = plt.subplots(figsize=(8, 3.5), facecolor=COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])

    ax.fill_between(dates, navs, alpha=0.15, color=COLORS["primary"])
    ax.plot(dates, navs, color=COLORS["primary"], linewidth=1.8)

    ax.set_title(f"{scheme_name}", fontsize=11, fontweight="bold", color=COLORS["text"], pad=12)
    ax.set_ylabel("NAV (₹)", fontsize=9, color=COLORS["text"])
    ax.tick_params(colors=COLORS["text"], labelsize=8)
    ax.grid(axis="y", color=COLORS["grid"], linewidth=0.5)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(COLORS["grid"])
    fig.autofmt_xdate(rotation=30)

    return _save(fig)


# ---------- Chart 2: SIP projection ----------

def sip_projection_chart(monthly: float, annual_return_pct: float, years: int,
                         stepup_pct: float = 0) -> str:
    """
    Month-by-month SIP projection showing invested vs total value.
    Returns PNG path.
    """
    i = (annual_return_pct / 100) / 12
    months_list = []
    invested_list = []
    value_list = []

    balance = 0.0
    invested = 0.0
    current_monthly = monthly

    for m in range(1, int(years) * 12 + 1):
        if stepup_pct > 0 and m > 1 and (m - 1) % 12 == 0:
            current_monthly *= (1 + stepup_pct / 100)
        invested += current_monthly
        balance = (balance + current_monthly) * (1 + i)
        months_list.append(m)
        invested_list.append(invested)
        value_list.append(balance)

    fig, ax = plt.subplots(figsize=(8, 4), facecolor=COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])

    ax.fill_between(months_list, invested_list, alpha=0.25, color=COLORS["invested"], label="Invested")
    ax.fill_between(months_list, invested_list, value_list, alpha=0.3, color=COLORS["gain"], label="Gains")
    ax.plot(months_list, value_list, color=COLORS["primary"], linewidth=2, label="Portfolio Value")
    ax.plot(months_list, invested_list, color=COLORS["invested"], linewidth=1.2, linestyle="--")

    # annotate final
    final_val = value_list[-1]
    final_inv = invested_list[-1]
    ax.annotate(_fmt_inr(final_val), xy=(months_list[-1], final_val),
                fontsize=10, fontweight="bold", color=COLORS["primary"],
                xytext=(-60, 10), textcoords="offset points")
    ax.annotate(_fmt_inr(final_inv), xy=(months_list[-1], final_inv),
                fontsize=9, color=COLORS["invested"],
                xytext=(-60, -15), textcoords="offset points")

    step_label = f" + {stepup_pct:.0f}% annual step-up" if stepup_pct else ""
    ax.set_title(
        f"SIP Projection: ₹{monthly:,.0f}/mo @ {annual_return_pct:.0f}% for {years}y{step_label}",
        fontsize=10, fontweight="bold", color=COLORS["text"], pad=12,
    )
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_fmt_inr))
    ax.set_xlabel("Months", fontsize=9, color=COLORS["text"])
    ax.tick_params(colors=COLORS["text"], labelsize=8)
    ax.grid(axis="y", color=COLORS["grid"], linewidth=0.5)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(COLORS["grid"])
    ax.legend(fontsize=8, framealpha=0.6)

    return _save(fig)


# ---------- Chart 3: SIP backtest ----------

def sip_backtest_chart(nav_data: List[Dict], monthly: float, years: float,
                       scheme_name: str) -> str:
    """
    Backtest chart: invested vs portfolio value over the real NAV window.
    """
    series = _parse_nav(nav_data)
    if len(series) < 12:
        return None

    end_date = series[-1][0]
    start_anchor = end_date - timedelta(days=int(365.25 * years))
    if start_anchor < series[0][0]:
        start_anchor = series[0][0]

    dates_plot, invested_plot, value_plot = [], [], []
    units = 0.0
    invested = 0.0
    months = max(1, round(years * 12))

    for m in range(months):
        target = start_anchor + timedelta(days=round(30.44 * m))
        if target > end_date:
            break
        buy = None
        for d, v in series:
            if d >= target:
                buy = (d, v)
                break
        if not buy:
            continue
        bd, bv = buy
        units += monthly / bv
        invested += monthly

        dates_plot.append(bd)
        invested_plot.append(invested)
        value_plot.append(units * bv)

    if not dates_plot:
        return None

    # extend to latest NAV
    latest_nav = series[-1][1]
    dates_plot.append(series[-1][0])
    invested_plot.append(invested)
    value_plot.append(units * latest_nav)

    fig, ax = plt.subplots(figsize=(8, 4), facecolor=COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])

    ax.fill_between(dates_plot, invested_plot, alpha=0.25, color=COLORS["invested"])
    ax.fill_between(dates_plot, invested_plot, value_plot, alpha=0.3, color=COLORS["gain"])
    ax.plot(dates_plot, value_plot, color=COLORS["primary"], linewidth=2, label="Portfolio Value")
    ax.plot(dates_plot, invested_plot, color=COLORS["invested"], linewidth=1.2, linestyle="--", label="Invested")

    ax.annotate(_fmt_inr(value_plot[-1]), xy=(dates_plot[-1], value_plot[-1]),
                fontsize=10, fontweight="bold", color=COLORS["primary"],
                xytext=(-60, 10), textcoords="offset points")

    ax.set_title(f"SIP Backtest: ₹{monthly:,.0f}/mo in {scheme_name}",
                 fontsize=10, fontweight="bold", color=COLORS["text"], pad=12)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_fmt_inr))
    ax.tick_params(colors=COLORS["text"], labelsize=8)
    ax.grid(axis="y", color=COLORS["grid"], linewidth=0.5)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(COLORS["grid"])
    ax.legend(fontsize=8, framealpha=0.6)
    fig.autofmt_xdate(rotation=30)

    return _save(fig)
