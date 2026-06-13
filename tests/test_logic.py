"""
Tests for the financial engine. Run: python3 tests/test_logic.py
Validates against hand-computed values and a synthetic NAV series with known growth.
"""
import sys, os
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calculators as c

PASS, FAIL = 0, 0
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {name}")
    else:
        FAIL += 1; print(f"  FAIL  {name}  {detail}")

print("== SIP future value ==")
# ₹10,000/mo, 12% p.a., 10y. Known good ~ ₹23.23 lakh (start-of-month).
r = c.sip_future_value(10000, 12, 10)
check("invested == 12,00,000", r["total_invested"] == 1200000, r)
check("FV in expected band (22.9–23.5L)", 2290000 < r["future_value"] < 2350000, r["future_value"])

print("== Goal round-trip (inverse of SIP) ==")
target = 2323391  # approx FV above
g = c.required_sip_for_goal(target, 12, 10)
back = c.sip_future_value(g["required_monthly_sip"], 12, 10)
check("required SIP reproduces target (±0.5%)",
      abs(back["future_value"] - target) / target < 0.005,
      f"got {back['future_value']} vs {target}")

print("== Step-up SIP > flat SIP ==")
flat = c.sip_future_value(10000, 12, 10)["future_value"]
step = c.stepup_sip_future_value(10000, 12, 10, 10)["future_value"]
check("step-up FV > flat FV", step > flat, f"step {step} vs flat {flat}")
check("0% step-up == flat (±0.1%)",
      abs(c.stepup_sip_future_value(10000, 12, 10, 0)["future_value"] - flat) / flat < 0.001)

print("== Lumpsum ==")
l = c.lumpsum_future_value(100000, 10, 7)
check("1L @10% for 7y ~ 1.948L", 194000 < l["future_value"] < 195000, l["future_value"])

print("== NAV parsing on real mfapi.in format ==")
real_sample = [
    {"date": "20-05-2026", "nav": "104.38260"},
    {"date": "19-05-2026", "nav": "104.42160"},
    {"date": "18-05-2026", "nav": "0"},          # zero -> skipped
    {"date": "bad", "nav": "x"},                  # malformed -> skipped
    {"date": "15-05-2026", "nav": "104.59680"},
]
series = c._parse_nav_series(real_sample)
check("parsed 3 valid rows, sorted oldest-first", len(series) == 3, series)
check("oldest first", series[0][0] < series[-1][0])

print("== Trailing returns + backtest on synthetic 10%/yr series ==")
# Build daily NAV growing at exactly 10% annual for 6 years, in mfapi format (newest first).
start = datetime(2020, 1, 1)
days = 365 * 6
daily_rate = (1.10) ** (1 / 365.25) - 1
synth = []
nav = 100.0
for day in range(days):
    d = start + timedelta(days=day)
    synth.append({"date": d.strftime("%d-%m-%Y"), "nav": f"{nav:.5f}"})
    nav *= (1 + daily_rate)
synth.reverse()  # newest first, like the real API

tr = c.trailing_returns(synth)
check("1y CAGR ~10%", tr["cagr_1y_pct"] is not None and 9.5 < tr["cagr_1y_pct"] < 10.5, tr.get("cagr_1y_pct"))
check("3y CAGR ~10%", tr["cagr_3y_pct"] is not None and 9.5 < tr["cagr_3y_pct"] < 10.5, tr.get("cagr_3y_pct"))
check("5y CAGR ~10%", tr["cagr_5y_pct"] is not None and 9.5 < tr["cagr_5y_pct"] < 10.5, tr.get("cagr_5y_pct"))

bt = c.sip_backtest(synth, 5000, 5)
check("backtest invested == 60k (60 installments)", bt["total_invested"] == 300000, bt)
check("backtest XIRR ~10% for 10% fund", bt["xirr_pct"] is not None and 9 < bt["xirr_pct"] < 11, bt.get("xirr_pct"))
check("backtest current value > invested", bt["current_value"] > bt["total_invested"])

print(f"\nRESULT: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
