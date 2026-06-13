"""
calculators.py
Pure financial math. No network. Fully unit-testable.

All rupee amounts are plain floats. Rates are annual percentages (e.g. 12 for 12%).
These are projections/illustrations, NOT guarantees of return.
"""
from datetime import datetime
from typing import List, Dict, Tuple


def _monthly_rate(annual_pct: float) -> float:
    return (annual_pct / 100.0) / 12.0


def sip_future_value(monthly: float, annual_return_pct: float, years: float) -> Dict:
    """
    Standard SIP future value, contributions at the START of each month.
    FV = P * [((1+i)^n - 1) / i] * (1+i)
    """
    n = round(years * 12)
    i = _monthly_rate(annual_return_pct)
    if i == 0:
        fv = monthly * n
    else:
        fv = monthly * (((1 + i) ** n - 1) / i) * (1 + i)
    invested = monthly * n
    return {
        "monthly_investment": round(monthly, 2),
        "years": years,
        "months": n,
        "assumed_annual_return_pct": annual_return_pct,
        "total_invested": round(invested, 2),
        "future_value": round(fv, 2),
        "wealth_gain": round(fv - invested, 2),
    }


def stepup_sip_future_value(monthly: float, annual_return_pct: float, years: int,
                            stepup_pct: float) -> Dict:
    """
    Step-up SIP: the monthly amount increases by stepup_pct at the start of every year.
    Computed year by year, contributions at start of month.
    """
    i = _monthly_rate(annual_return_pct)
    balance = 0.0
    invested = 0.0
    current_monthly = monthly
    for _ in range(int(years)):
        for _m in range(12):
            balance = (balance + current_monthly) * (1 + i)
            invested += current_monthly
        current_monthly *= (1 + stepup_pct / 100.0)
    return {
        "starting_monthly": round(monthly, 2),
        "annual_stepup_pct": stepup_pct,
        "years": years,
        "assumed_annual_return_pct": annual_return_pct,
        "final_monthly": round(current_monthly, 2),
        "total_invested": round(invested, 2),
        "future_value": round(balance, 2),
        "wealth_gain": round(balance - invested, 2),
    }


def required_sip_for_goal(target_amount: float, annual_return_pct: float, years: float) -> Dict:
    """
    Reverse SIP: monthly investment needed to reach a target corpus.
    P = FV * i / (((1+i)^n - 1) * (1+i))
    """
    n = round(years * 12)
    i = _monthly_rate(annual_return_pct)
    if i == 0:
        monthly = target_amount / n
    else:
        monthly = target_amount * i / (((1 + i) ** n - 1) * (1 + i))
    return {
        "target_amount": round(target_amount, 2),
        "years": years,
        "months": n,
        "assumed_annual_return_pct": annual_return_pct,
        "required_monthly_sip": round(monthly, 2),
        "total_invested": round(monthly * n, 2),
    }


def lumpsum_future_value(amount: float, annual_return_pct: float, years: float) -> Dict:
    fv = amount * (1 + annual_return_pct / 100.0) ** years
    return {
        "lumpsum": round(amount, 2),
        "years": years,
        "assumed_annual_return_pct": annual_return_pct,
        "future_value": round(fv, 2),
        "wealth_gain": round(fv - amount, 2),
    }


# ---------- Real NAV-history based metrics ----------

def _parse_nav_series(nav_data: List[Dict]) -> List[Tuple[datetime, float]]:
    """
    Convert mfapi.in 'data' list ({date:'DD-MM-YYYY', nav:'123.45'}) into a
    list of (datetime, float) sorted OLDEST first. Skips bad/zero rows.
    """
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


def _nav_on_or_before(series: List[Tuple[datetime, float]], target: datetime) -> Tuple[datetime, float]:
    """Find the NAV on the latest date <= target. series must be oldest-first."""
    chosen = None
    for d, v in series:
        if d <= target:
            chosen = (d, v)
        else:
            break
    return chosen


def trailing_returns(nav_data: List[Dict]) -> Dict:
    """
    CAGR for 1y / 3y / 5y and absolute since-inception, from real NAV history.
    """
    series = _parse_nav_series(nav_data)
    if len(series) < 2:
        return {"error": "Not enough NAV history to compute returns."}

    start_date, start_nav = series[0]
    end_date, end_nav = series[-1]
    total_years = (end_date - start_date).days / 365.25

    result = {
        "latest_nav": round(end_nav, 4),
        "latest_nav_date": end_date.strftime("%d-%m-%Y"),
        "history_span_years": round(total_years, 2),
    }

    from datetime import timedelta
    for label, yrs in [("1y", 1), ("3y", 3), ("5y", 5)]:
        past = _nav_on_or_before(series, end_date - timedelta(days=round(365.25 * yrs)))
        if past and past[0] >= start_date and (end_date - past[0]).days >= 300 * yrs / 1:
            pd, pv = past
            actual_yrs = (end_date - pd).days / 365.25
            cagr = ((end_nav / pv) ** (1 / actual_yrs) - 1) * 100 if actual_yrs > 0 else None
            result[f"cagr_{label}_pct"] = round(cagr, 2) if cagr is not None else None
        else:
            result[f"cagr_{label}_pct"] = None  # not enough history

    if total_years > 0:
        result["cagr_since_inception_pct"] = round(((end_nav / start_nav) ** (1 / total_years) - 1) * 100, 2)
    return result


def _xirr(cashflows: List[Tuple[datetime, float]], guess: float = 0.1) -> float:
    """
    XIRR via bisection (no scipy). cashflows: (date, amount), outflows negative,
    final inflow positive. Returns annualised rate as a decimal, or None.
    """
    if len(cashflows) < 2:
        return None
    t0 = cashflows[0][0]

    def npv(rate: float) -> float:
        total = 0.0
        for d, amt in cashflows:
            yrs = (d - t0).days / 365.25
            total += amt / ((1 + rate) ** yrs)
        return total

    low, high = -0.9999, 10.0
    f_low, f_high = npv(low), npv(high)
    if f_low * f_high > 0:
        return None  # no sign change in range
    for _ in range(200):
        mid = (low + high) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-6:
            return mid
        if f_low * f_mid < 0:
            high = mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2


def sip_backtest(nav_data: List[Dict], monthly: float, years: float) -> Dict:
    """
    What a real monthly SIP into THIS fund would have done over the last `years`,
    using actual NAV history. Buys units on the first available NAV on/after each
    monthly anchor date. Reports invested, current value, absolute return, and XIRR.
    """
    series = _parse_nav_series(nav_data)
    if len(series) < 12:
        return {"error": "Not enough NAV history for a backtest."}

    from datetime import timedelta
    end_date, end_nav = series[-1]
    start_anchor = end_date - timedelta(days=round(365.25 * years))
    if start_anchor < series[0][0]:
        start_anchor = series[0][0]
        years = (end_date - start_anchor).days / 365.25

    # build monthly purchase dates
    units = 0.0
    invested = 0.0
    cashflows: List[Tuple[datetime, float]] = []
    anchor = start_anchor
    # iterate month by month
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
        bought = monthly / bv
        units += bought
        invested += monthly
        cashflows.append((bd, -monthly))

    if invested == 0:
        return {"error": "No purchases could be simulated in the given window."}

    current_value = units * end_nav
    cashflows.append((end_date, current_value))
    rate = _xirr(cashflows)
    abs_return = (current_value - invested) / invested * 100

    return {
        "monthly_investment": round(monthly, 2),
        "window_years": round(years, 2),
        "installments": len(cashflows) - 1,
        "total_invested": round(invested, 2),
        "units_accumulated": round(units, 4),
        "current_value": round(current_value, 2),
        "absolute_return_pct": round(abs_return, 2),
        "xirr_pct": round(rate * 100, 2) if rate is not None else None,
        "note": "Past performance from real NAV history. Not indicative of future returns.",
    }
