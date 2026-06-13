"""
pdf_report.py
Generates a clean one-page SIP Investment Plan as a downloadable PDF.
Uses reportlab Platypus for a professional layout.
"""
import os
import uuid
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, HRFlowable
)

CHART_DIR = os.path.join(os.path.dirname(__file__), "tmp_charts")
PDF_DIR = os.path.join(os.path.dirname(__file__), "tmp_pdfs")
os.makedirs(PDF_DIR, exist_ok=True)

# colors
INDIGO = HexColor("#6366f1")
DARK = HexColor("#1e293b")
SLATE = HexColor("#64748b")
LIGHT = HexColor("#f1f5f9")
WHITE = HexColor("#ffffff")


def _fmt_inr(x):
    if x is None:
        return "N/A"
    if abs(x) >= 1e7:
        return f"\u20b9{x/1e7:,.2f} Cr"
    if abs(x) >= 1e5:
        return f"\u20b9{x/1e5:,.2f} L"
    return f"\u20b9{x:,.0f}"


def _pct(x):
    return f"{x:.1f}%" if x is not None else "N/A"


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("MainTitle", parent=ss["Title"], fontSize=18, textColor=INDIGO,
                          spaceAfter=2*mm, fontName="Helvetica-Bold"))
    ss.add(ParagraphStyle("Sub", parent=ss["Normal"], fontSize=9, textColor=SLATE,
                          alignment=TA_CENTER, spaceAfter=4*mm))
    ss.add(ParagraphStyle("SectionHead", parent=ss["Heading2"], fontSize=12, textColor=INDIGO,
                          spaceBefore=5*mm, spaceAfter=2*mm, fontName="Helvetica-Bold"))
    ss.add(ParagraphStyle("Body", parent=ss["Normal"], fontSize=9.5, textColor=DARK,
                          spaceAfter=2*mm, leading=13))
    ss.add(ParagraphStyle("Disclaimer", parent=ss["Normal"], fontSize=7, textColor=SLATE,
                          spaceBefore=4*mm, leading=9))
    ss.add(ParagraphStyle("CellText", parent=ss["Normal"], fontSize=9, textColor=DARK, leading=11))
    ss.add(ParagraphStyle("CellBold", parent=ss["Normal"], fontSize=9, textColor=DARK,
                          fontName="Helvetica-Bold", leading=11))
    return ss


def generate_plan_pdf(
    user_profile: dict = None,
    sip_projection: dict = None,
    stepup_projection: dict = None,
    goal_plan: dict = None,
    fund_analyses: list = None,
    backtest: dict = None,
    chart_paths: list = None,
) -> str:
    """
    Build a one-page SIP plan PDF. All params are optional dicts from prior tool calls.
    Returns the PDF file path.
    """
    path = os.path.join(PDF_DIR, f"sip_plan_{uuid.uuid4().hex[:8]}.pdf")
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=18*mm, rightMargin=18*mm,
                            topMargin=15*mm, bottomMargin=12*mm)
    ss = _styles()
    story = []

    # --- Header ---
    story.append(Paragraph("SIP Saathi \u2014 Your Investment Plan", ss["MainTitle"]))
    story.append(Paragraph(f"Generated on {datetime.now().strftime('%d %b %Y, %I:%M %p')}", ss["Sub"]))
    story.append(HRFlowable(width="100%", thickness=0.8, color=INDIGO, spaceAfter=3*mm))

    # --- User Profile ---
    if user_profile:
        story.append(Paragraph("Your Profile", ss["SectionHead"]))
        bits = []
        if user_profile.get("name"):
            bits.append(f"<b>Name:</b> {user_profile['name']}")
        if user_profile.get("risk"):
            bits.append(f"<b>Risk Appetite:</b> {user_profile['risk'].title()}")
        if user_profile.get("monthly_budget"):
            bits.append(f"<b>Monthly Budget:</b> {_fmt_inr(user_profile['monthly_budget'])}")
        if user_profile.get("goal"):
            bits.append(f"<b>Goal:</b> {user_profile['goal']}")
        if user_profile.get("horizon_years"):
            bits.append(f"<b>Horizon:</b> {user_profile['horizon_years']} years")
        story.append(Paragraph("  \u2022  ".join(bits), ss["Body"]))

    # --- SIP Projection Table ---
    has_proj = sip_projection or stepup_projection or goal_plan
    if has_proj:
        story.append(Paragraph("SIP Projections", ss["SectionHead"]))
        header = [Paragraph("<b>Metric</b>", ss["CellBold"]),
                  Paragraph("<b>Flat SIP</b>", ss["CellBold"]),
                  Paragraph("<b>Step-Up SIP</b>", ss["CellBold"])]
        rows = [header]

        flat = sip_projection or {}
        step = stepup_projection or {}

        def row(label, fk, sk):
            return [Paragraph(label, ss["CellText"]),
                    Paragraph(str(flat.get(fk, "—")), ss["CellText"]),
                    Paragraph(str(step.get(sk, "—")), ss["CellText"])]

        rows.append(row("Monthly Investment", "monthly_investment", "starting_monthly"))
        if step:
            rows.append([Paragraph("Annual Step-Up", ss["CellText"]),
                         Paragraph("—", ss["CellText"]),
                         Paragraph(f"{step.get('annual_stepup_pct', 0)}%", ss["CellText"])])
        rows.append([Paragraph("Assumed Return", ss["CellText"]),
                     Paragraph(_pct(flat.get("assumed_annual_return_pct")), ss["CellText"]),
                     Paragraph(_pct(step.get("assumed_annual_return_pct")), ss["CellText"])])
        rows.append([Paragraph("Tenure", ss["CellText"]),
                     Paragraph(f"{flat.get('years','—')} yrs", ss["CellText"]),
                     Paragraph(f"{step.get('years','—')} yrs", ss["CellText"])])
        rows.append([Paragraph("<b>Total Invested</b>", ss["CellBold"]),
                     Paragraph(f"<b>{_fmt_inr(flat.get('total_invested'))}</b>", ss["CellBold"]),
                     Paragraph(f"<b>{_fmt_inr(step.get('total_invested'))}</b>", ss["CellBold"])])
        rows.append([Paragraph("<b>Future Value</b>", ss["CellBold"]),
                     Paragraph(f"<b>{_fmt_inr(flat.get('future_value'))}</b>", ss["CellBold"]),
                     Paragraph(f"<b>{_fmt_inr(step.get('future_value'))}</b>", ss["CellBold"])])
        rows.append([Paragraph("<b>Wealth Gain</b>", ss["CellBold"]),
                     Paragraph(f"<b>{_fmt_inr(flat.get('wealth_gain'))}</b>", ss["CellBold"]),
                     Paragraph(f"<b>{_fmt_inr(step.get('wealth_gain'))}</b>", ss["CellBold"])])

        t = Table(rows, colWidths=[45*mm, 50*mm, 50*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), INDIGO),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("BACKGROUND", (0, 1), (-1, -1), LIGHT),
            ("GRID", (0, 0), (-1, -1), 0.4, HexColor("#cbd5e1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(t)

    # --- Goal Planner ---
    if goal_plan:
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph(
            f"To reach a goal of <b>{_fmt_inr(goal_plan.get('target_amount'))}</b> in "
            f"<b>{goal_plan.get('years')} years</b> at {_pct(goal_plan.get('assumed_annual_return_pct'))}: "
            f"you need <b>{_fmt_inr(goal_plan.get('required_monthly_sip'))}/month</b>.",
            ss["Body"]))

    # --- Fund Analysis ---
    if fund_analyses:
        story.append(Paragraph("Fund Performance (Real Returns)", ss["SectionHead"]))
        header = [Paragraph(f"<b>{h}</b>", ss["CellBold"])
                  for h in ["Fund", "Category", "1Y", "3Y", "5Y"]]
        rows = [header]
        for fa in fund_analyses[:4]:
            ret = fa.get("returns", {})
            rows.append([
                Paragraph(fa.get("scheme_name", "?")[:40], ss["CellText"]),
                Paragraph((fa.get("category") or "")[:25], ss["CellText"]),
                Paragraph(_pct(ret.get("cagr_1y_pct")), ss["CellText"]),
                Paragraph(_pct(ret.get("cagr_3y_pct")), ss["CellText"]),
                Paragraph(_pct(ret.get("cagr_5y_pct")), ss["CellText"]),
            ])
        t = Table(rows, colWidths=[55*mm, 35*mm, 20*mm, 20*mm, 20*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), INDIGO),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("GRID", (0, 0), (-1, -1), 0.4, HexColor("#cbd5e1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(t)

    # --- Backtest ---
    if backtest and "error" not in backtest:
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph(
            f"<b>Backtest ({backtest.get('scheme_name','')}):</b> "
            f"{_fmt_inr(backtest.get('monthly_investment'))}/mo for {backtest.get('window_years')} yrs \u2192 "
            f"Invested {_fmt_inr(backtest.get('total_invested'))}, "
            f"Value {_fmt_inr(backtest.get('current_value'))} "
            f"(XIRR {_pct(backtest.get('xirr_pct'))})",
            ss["Body"],
        ))

    # --- Charts ---
    if chart_paths:
        story.append(Paragraph("Charts", ss["SectionHead"]))
        for cp in chart_paths:
            if cp and os.path.exists(cp):
                try:
                    img = Image(cp, width=160*mm, height=65*mm)
                    story.append(img)
                    story.append(Spacer(1, 2*mm))
                except Exception:
                    pass

    # --- Disclaimer ---
    story.append(HRFlowable(width="100%", thickness=0.5, color=SLATE, spaceBefore=3*mm))
    story.append(Paragraph(
        "Disclaimer: This plan is for educational and illustrative purposes only. "
        "SIP Saathi is NOT a SEBI-registered investment adviser. Projections are based on assumed "
        "rates of return and do not guarantee actual results. Past performance does not guarantee "
        "future returns. Please consult a SEBI-registered adviser before making investment decisions.",
        ss["Disclaimer"],
    ))

    doc.build(story)
    return path
