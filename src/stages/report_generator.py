"""
Audit Report Generator — Stage 6C + 6D
=======================================

Produces a PDF and an HTML compliance audit report from the violation_report
and rule_explanations produced by the LangGraph pipeline.

Usage
-----
    from src.stages.report_generator import generate_reports

    paths = generate_reports(state, output_dir="data/")
    print(paths["pdf"], paths["html"])
"""
from __future__ import annotations

import html as _html_mod
import json
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.utils.logger import setup_logger

log = setup_logger(__name__)


def _ensure_list(val: Any) -> List[str]:
    """Guarantee remediation_steps is always a plain list of strings."""
    if isinstance(val, list):
        # Detect list-of-single-characters (a string erroneously converted
        # to list via list(string) at some point). Rejoin and re-parse.
        if val and all(isinstance(s, str) and len(s) <= 1 for s in val):
            joined = "".join(val).strip()
            if joined:
                import json as _json
                try:
                    parsed = _json.loads(joined)
                    if isinstance(parsed, list):
                        return [str(s) for s in parsed]
                except Exception:
                    pass
                # Not valid JSON — return the rejoined string as a single step
                return [joined]
            return []
        return [str(s) for s in val]
    if isinstance(val, str):
        import json as _json
        try:
            parsed = _json.loads(val)
            if isinstance(parsed, list):
                return [str(s) for s in parsed]
        except Exception:
            pass
        # Fallback: treat the whole string as one step if non-empty
        return [val] if val.strip() else []
    return []

# ---------------------------------------------------------------------------
# Colour & grade helpers
# ---------------------------------------------------------------------------

_GRADE_COLOR_HEX = {"A": "#22c55e", "B": "#84cc16", "C": "#eab308", "D": "#f97316", "F": "#ef4444"}
_SEV_COLOR_HEX   = {"HIGH": "#ef4444", "MEDIUM": "#f97316", "LOW": "#eab308", "": "#6b7280"}


def _grade_color(grade: str) -> str:
    return _GRADE_COLOR_HEX.get(grade, "#6b7280")


def _sev_color(sev: str) -> str:
    return _SEV_COLOR_HEX.get(sev.upper() if sev else "", "#6b7280")


def _score_to_grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 45:
        return "D"
    return "F"


# ═══════════════════════════════════════════════════════════════════════════════
#  6C — PDF / ReportLab
# ═══════════════════════════════════════════════════════════════════════════════

def build_scan_report_pdf(
    report: Dict[str, Any],
    rule_explanations: Dict[str, Any],
    output_path: str | Path,
) -> str:
    """Generate a multi-page PDF audit report.  Returns the absolute path."""

    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            HRFlowable,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as e:
        log.error(f"reportlab not installed — cannot build PDF: {e}")
        return ""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Doc setup ────────────────────────────────────────────────────────────
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=22 * mm,
        bottomMargin=22 * mm,
        title="AML Compliance Scan Report",
        author="Data Compliance Agent",
    )

    # ── Styles ───────────────────────────────────────────────────────────────
    base = getSampleStyleSheet()

    def _style(name: str, **kwargs) -> ParagraphStyle:
        s = ParagraphStyle(name, parent=base["Normal"], **kwargs)
        return s

    st_title   = _style("ReportTitle",   fontSize=26, leading=32, textColor=colors.HexColor("#0f172a"), spaceAfter=6, alignment=TA_CENTER, fontName="Helvetica-Bold")
    st_sub     = _style("ReportSub",     fontSize=13, leading=18, textColor=colors.HexColor("#64748b"), spaceAfter=4, alignment=TA_CENTER)
    st_h1      = _style("H1",            fontSize=16, leading=20, textColor=colors.HexColor("#1e3a5f"), spaceAfter=4, spaceBefore=12, fontName="Helvetica-Bold")
    st_h2      = _style("H2",            fontSize=12, leading=16, textColor=colors.HexColor("#334155"), spaceAfter=3, spaceBefore=8,  fontName="Helvetica-Bold")
    st_body    = _style("Body",          fontSize=9,  leading=13, textColor=colors.HexColor("#374151"), spaceAfter=3)
    st_body_sm = _style("BodySm",        fontSize=8,  leading=11, textColor=colors.HexColor("#4b5563"), spaceAfter=2)
    st_bold    = _style("BodyBold",      fontSize=9,  leading=13, textColor=colors.HexColor("#111827"), spaceAfter=2, fontName="Helvetica-Bold")
    st_label   = _style("Label",         fontSize=8,  leading=10, textColor=colors.HexColor("#6b7280"), spaceAfter=1)
    st_sev_hi  = _style("SevHigh",       fontSize=9,  leading=12, textColor=colors.HexColor("#b91c1c"), fontName="Helvetica-Bold")
    st_sev_md  = _style("SevMedium",     fontSize=9,  leading=12, textColor=colors.HexColor("#c2410c"), fontName="Helvetica-Bold")
    st_sev_lo  = _style("SevLow",        fontSize=9,  leading=12, textColor=colors.HexColor("#92400e"))
    st_bullet  = _style("Bullet",        fontSize=8,  leading=11, textColor=colors.HexColor("#374151"), leftIndent=12, spaceAfter=2)

    _SEV_PARA_STYLE = {"HIGH": st_sev_hi, "MEDIUM": st_sev_md, "LOW": st_sev_lo}

    def _sev_para(sev: str) -> Paragraph:
        return Paragraph(sev or "—", _SEV_PARA_STYLE.get(sev, st_body))

    def HR(color="#CBD5E1"):
        return HRFlowable(width="100%", thickness=0.5, color=colors.HexColor(color), spaceAfter=6, spaceBefore=3)

    # ── Extract summary data ─────────────────────────────────────────────────
    summary   = report.get("summary", {})
    scan_id   = report.get("scan_id", "—")
    generated = report.get("generated_at", datetime.now(timezone.utc).isoformat())[:19].replace("T", " ")
    total_v   = summary.get("total_violations", 0)
    score     = float(summary.get("compliance_score", 0.0))
    grade     = summary.get("compliance_grade") or _score_to_grade(score)
    passing   = summary.get("rules_passing", "?")
    failing   = summary.get("rules_failing", "?")
    total_r   = summary.get("total_rules_checked", "?")
    avg_conf  = float(summary.get("avg_confidence", 0.0))

    by_rule   = report.get("by_rule", {})
    by_table  = report.get("by_table", {})
    nr_count  = len(report.get("needs_review", []))

    story: List[Any] = []

    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║  COVER PAGE                                                        ║
    # ╚══════════════════════════════════════════════════════════════════════╝
    story.append(Spacer(1, 30 * mm))
    story.append(Paragraph("AML Compliance Scan", st_title))
    story.append(Paragraph("Audit Report", _style("AuditSub", fontSize=20, leading=26, alignment=TA_CENTER, textColor=colors.HexColor("#3b82f6"), fontName="Helvetica-Bold")))
    story.append(Spacer(1, 6 * mm))
    story.append(HR("#93C5FD"))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"Scan ID: {scan_id}", st_sub))
    story.append(Paragraph(f"Generated: {generated} UTC", st_sub))
    story.append(Spacer(1, 10 * mm))

    # Compliance score box
    gc = _grade_color(grade)
    score_tbl = Table(
        [[Paragraph(f"{score:.1f}%", _style("ScoreNum", fontSize=36, leading=42, alignment=TA_CENTER, fontName="Helvetica-Bold", textColor=colors.HexColor(gc))),
          Paragraph(f"Grade<br/><font size='28'><b>{grade}</b></font>", _style("GradeCell", fontSize=14, leading=28, alignment=TA_CENTER, textColor=colors.HexColor(gc)))]],
        colWidths=[80 * mm, 60 * mm],
    )
    score_tbl.setStyle(TableStyle([
        ("ALIGN",     (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",    (0, 0), (-1, -1), "MIDDLE"),
        ("BOX",       (0, 0), (-1, -1), 1.5, colors.HexColor(gc)),
        ("BACKGROUND",(0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("ROUNDEDCORNERS", [6]),
        ("TOPPADDING",  (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING",(0,0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ("RIGHTPADDING",(0, 0), (-1, -1), 16),
    ]))
    story.append(score_tbl)
    story.append(Spacer(1, 8 * mm))

    cov_data = [
        ["Total Violations", "Rules Checked", "Rules Passing", "Rules Failing", "Avg Confidence"],
        [str(total_v), str(total_r), str(passing), str(failing), f"{avg_conf:.2f}"],
    ]
    cov_tbl = Table(cov_data, colWidths=[38 * mm] * 5)
    cov_tbl.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
        ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, -1), 8),
        ("ALIGN",       (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f1f5f9"), colors.white]),
        ("GRID",        (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
    ]))
    story.append(cov_tbl)
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        "This report was generated automatically by the Data Compliance Agent. "
        "It presents findings from a rule-based scan of financial transaction data "
        "against the AML Compliance Policy. Each violation has been evaluated for "
        "severity and assigned remediation guidance.",
        st_body,
    ))
    story.append(PageBreak())

    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║  EXECUTIVE SUMMARY                                                 ║
    # ╚══════════════════════════════════════════════════════════════════════╝
    story.append(Paragraph("Executive Summary", st_h1))
    story.append(HR())

    exec_rows = [
        ("Compliance Score",    f"{score:.1f}%  (Grade {grade})"),
        ("Total Violations",    str(total_v)),
        ("Rules Assessed",      str(total_r)),
        ("Rules Passing",       str(passing)),
        ("Rules Failing",       str(failing)),
        ("Needs Human Review",  str(nr_count)),
        ("Average Confidence",  f"{avg_conf:.2f}"),
        ("Tables Scanned",      str(summary.get("tables_scanned", summary.get("tables_with_violations", "?")))),
    ]
    exec_tbl = Table([[Paragraph(k, st_bold), Paragraph(v, st_body)] for k, v in exec_rows],
                     colWidths=[60 * mm, 110 * mm])
    exec_tbl.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
        ("GRID",  (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
    ]))
    story.append(exec_tbl)
    story.append(Spacer(1, 5 * mm))

    if total_v > 0:
        story.append(Paragraph(
            f"A total of <b>{total_v}</b> compliance violations were detected across "
            f"<b>{len(by_table)}</b> table(s). "
            f"<b>{failing}</b> of {total_r} rules triggered at least one violation. "
            f"The compliance score of <b>{score:.1f}%</b> reflects the proportion of "
            f"rules with zero violations.",
            st_body,
        ))
    else:
        story.append(Paragraph("No violations detected. All rules passed.", st_body))

    story.append(PageBreak())

    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║  RULES SUMMARY TABLE                                               ║
    # ╚══════════════════════════════════════════════════════════════════════╝
    story.append(Paragraph("Rules Summary", st_h1))
    story.append(HR())

    hdr = [Paragraph(h, _style(f"TH_{h}", fontSize=8, textColor=colors.white, fontName="Helvetica-Bold", alignment=TA_CENTER))
           for h in ["Rule ID", "Violations", "Severity", "Status", "Rule Text"]]
    rules_rows = [hdr]
    for rid, entry in sorted(by_rule.items(), key=lambda x: -x[1]["count"]):
        count  = entry.get("count", 0)
        sev    = entry.get("severity", "")
        text   = (entry.get("rule_text") or "")[:80]
        status = "FAIL" if count > 0 else "PASS"
        status_para = Paragraph(
            f"<font color='{'#b91c1c' if status == 'FAIL' else '#15803d'}'><b>{status}</b></font>",
            st_body,
        )
        rules_rows.append([
            Paragraph(rid, st_bold),
            Paragraph(str(count), _style("CntCell", fontSize=9, alignment=TA_CENTER, textColor=colors.HexColor("#b91c1c" if count > 0 else "#15803d"), fontName="Helvetica-Bold")),
            _sev_para(sev),
            status_para,
            Paragraph(text, st_body_sm),
        ])

    rules_tbl = Table(rules_rows, colWidths=[22 * mm, 20 * mm, 20 * mm, 15 * mm, 93 * mm])
    rules_tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
        ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
        ("GRID",         (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
        ("ALIGN",        (1, 0), (2, -1), "CENTER"),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
    ]))
    story.append(rules_tbl)
    story.append(PageBreak())

    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║  PER-RULE DETAIL                                                   ║
    # ╚══════════════════════════════════════════════════════════════════════╝
    story.append(Paragraph("Rule-by-Rule Detail", st_h1))
    story.append(HR())

    # Sort by severity HIGH → MEDIUM → LOW → unknown, then by count desc
    sev_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "": 3}
    sorted_rules = sorted(
        by_rule.items(),
        key=lambda kv: (sev_order.get(kv[1].get("severity", ""), 3), -kv[1].get("count", 0)),
    )

    for rid, entry in sorted_rules:
        count  = entry.get("count", 0)
        sev    = entry.get("severity", "")
        expl   = entry.get("explanation", "")
        clause = entry.get("policy_clause", "")
        steps  = _ensure_list(entry.get("remediation_steps"))
        risk   = entry.get("risk_description", "")
        rtext  = entry.get("rule_text", "")

        sc = colors.HexColor(_sev_color(sev))
        story.append(Paragraph(f"{rid}", _style(f"RuleTitle_{rid}", fontSize=12, fontName="Helvetica-Bold", textColor=sc, spaceBefore=6)))
        story.append(Paragraph(rtext[:120], st_body_sm))
        story.append(Spacer(1, 2 * mm))

        detail_rows = []
        if sev:
            detail_rows.append([Paragraph("Severity", st_label), _sev_para(sev)])
        detail_rows.append([Paragraph("Violations", st_label), Paragraph(str(count), st_bold)])
        if clause:
            detail_rows.append([Paragraph("Policy Clause", st_label), Paragraph(clause, st_body)])
        if expl:
            detail_rows.append([Paragraph("Explanation", st_label), Paragraph(expl[:400], st_body)])
        if risk:
            detail_rows.append([Paragraph("Risk", st_label), Paragraph(risk[:300], st_body)])

        if detail_rows:
            det_tbl = Table(detail_rows, colWidths=[30 * mm, 140 * mm])
            det_tbl.setStyle(TableStyle([
                ("VALIGN",       (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING",   (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
                ("LEFTPADDING",  (0, 0), (-1, -1), 4),
                ("LINEBELOW",    (0, -1), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
            ]))
            story.append(det_tbl)

        if steps:
            story.append(Paragraph("Remediation Steps:", _style("RemTitle", fontSize=8, fontName="Helvetica-Bold", textColor=colors.HexColor("#1e3a5f"), spaceBefore=3)))
            for i, step in enumerate(steps, 1):
                story.append(Paragraph(f"{i}. {step}", st_bullet))

        story.append(HR("#e2e8f0"))

    story.append(PageBreak())

    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║  APPENDIX — BY TABLE                                               ║
    # ╚══════════════════════════════════════════════════════════════════════╝
    story.append(Paragraph("Appendix: Violations by Table", st_h1))
    story.append(HR())

    if by_table:
        tbl_data = [[Paragraph(h, _style(f"ATH{h}", fontSize=8, textColor=colors.white, fontName="Helvetica-Bold")) for h in ["Table", "Violations"]]]
        for tbl_name, tdata in sorted(by_table.items(), key=lambda x: -x[1].get("count", 0)):
            tbl_data.append([Paragraph(tbl_name, st_body), Paragraph(str(tdata.get("count", 0)), st_bold)])
        app_tbl = Table(tbl_data, colWidths=[110 * mm, 60 * mm])
        app_tbl.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
            ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
            ("GRID",         (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
            ("TOPPADDING",   (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
            ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ]))
        story.append(app_tbl)
    else:
        story.append(Paragraph("No table data available.", st_body))

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(
        f"End of report.  Generated by Data Compliance Agent on {generated} UTC.",
        _style("Footer", fontSize=8, textColor=colors.HexColor("#9ca3af"), alignment=TA_CENTER),
    ))

    doc.build(story)
    log.info(f"PDF report written to {output_path}")
    return str(output_path)


# ═══════════════════════════════════════════════════════════════════════════════
#  6D — HTML export
# ═══════════════════════════════════════════════════════════════════════════════

def build_scan_report_html(
    report: Dict[str, Any],
    rule_explanations: Dict[str, Any],
    output_path: str | Path,
) -> str:
    """Generate an HTML compliance audit report.  Returns the absolute path."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    summary   = report.get("summary", {})
    scan_id   = report.get("scan_id", "—")
    generated = report.get("generated_at", datetime.now(timezone.utc).isoformat())[:19].replace("T", " ")
    total_v   = summary.get("total_violations", 0)
    score     = float(summary.get("compliance_score", 0.0))
    grade     = summary.get("compliance_grade") or _score_to_grade(score)
    passing   = summary.get("rules_passing", "?")
    failing   = summary.get("rules_failing", "?")
    total_r   = summary.get("total_rules_checked", "?")
    avg_conf  = float(summary.get("avg_confidence", 0.0))
    nr_count  = len(report.get("needs_review", []))

    by_rule  = report.get("by_rule", {})
    by_table = report.get("by_table", {})

    gc = _grade_color(grade)

    def esc(s: Any) -> str:
        return _html_mod.escape(str(s or ""))

    # ── Rules summary rows ───────────────────────────────────────────────────
    rules_rows_html = ""
    sev_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "": 3}
    sorted_rules = sorted(
        by_rule.items(),
        key=lambda kv: (sev_order.get(kv[1].get("severity", ""), 3), -kv[1].get("count", 0)),
    )

    for rid, entry in sorted_rules:
        count  = entry.get("count", 0)
        sev    = entry.get("severity", "")
        text   = esc(entry.get("rule_text", ""))[:100]
        status = "FAIL" if count > 0 else "PASS"
        st_color = "#dc2626" if status == "FAIL" else "#16a34a"
        sc = _sev_color(sev)
        rules_rows_html += f"""
        <tr>
          <td class="font-mono text-sm font-semibold">{esc(rid)}</td>
          <td class="text-center font-bold" style="color:{st_color}">{count}</td>
          <td style="color:{sc}; font-weight:600">{esc(sev) or "—"}</td>
          <td style="color:{st_color}; font-weight:700">{status}</td>
          <td class="text-gray">{text}</td>
        </tr>"""

    # ── Rule detail cards ────────────────────────────────────────────────────
    rule_cards_html = ""
    for rid, entry in sorted_rules:
        count  = entry.get("count", 0)
        sev    = entry.get("severity", "")
        expl   = esc(entry.get("explanation", ""))
        clause = esc(entry.get("policy_clause", ""))
        steps  = _ensure_list(entry.get("remediation_steps"))
        risk   = esc(entry.get("risk_description", ""))
        rtext  = esc(entry.get("rule_text", ""))
        sc = _sev_color(sev)
        status = "FAIL" if count > 0 else "PASS"
        st_color = "#dc2626" if status == "FAIL" else "#16a34a"

        steps_html = ""
        if steps:
            items = "".join(f"<li>{esc(s)}</li>" for s in steps)
            steps_html = f"<div class='section-label'>Remediation Steps</div><ol class='steps-list'>{items}</ol>"

        rule_cards_html += f"""
        <div class="rule-card" style="border-left: 4px solid {sc}">
          <div class="rule-header">
            <span class="rule-id">{esc(rid)}</span>
            <span class="badge" style="background:{sc}; color:white">{esc(sev) or "N/A"}</span>
            <span class="badge" style="background:{st_color}; color:white">{status}</span>
            <span class="violation-count">{count} violations</span>
          </div>
          <p class="rule-text">{rtext[:150]}</p>
          {"<div class='section-label'>Explanation</div><p>" + expl + "</p>" if expl else ""}
          {"<div class='section-label'>Policy Clause</div><p>" + clause + "</p>" if clause else ""}
          {"<div class='section-label'>Risk Description</div><p>" + risk + "</p>" if risk else ""}
          {steps_html}
        </div>"""

    # ── By table rows ────────────────────────────────────────────────────────
    table_rows_html = ""
    for tbl_name, tdata in sorted(by_table.items(), key=lambda x: -x[1].get("count", 0)):
        cnt = tdata.get("count", 0)
        table_rows_html += f"<tr><td>{esc(tbl_name)}</td><td class='text-center font-bold' style='color:#dc2626'>{cnt}</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>AML Compliance Scan Report — {esc(scan_id)}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
           background: #f1f5f9; color: #1e293b; font-size: 14px; line-height: 1.6; }}
    .container {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px; }}

    /* ── Header ── */
    .report-header {{ background: linear-gradient(135deg, #1e3a5f 0%, #1e40af 100%);
                      color: white; padding: 40px 32px; border-radius: 12px; margin-bottom: 28px; text-align: center; }}
    .report-header h1 {{ font-size: 2rem; font-weight: 800; margin-bottom: 4px; }}
    .report-header .subtitle {{ font-size: 1rem; opacity: 0.8; margin-bottom: 16px; }}
    .report-header .meta {{ font-size: 0.85rem; opacity: 0.65; }}

    /* ── Score card ── */
    .score-card {{ display: inline-flex; align-items: center; gap: 24px;
                   background: rgba(255,255,255,0.12); border: 2px solid rgba(255,255,255,0.25);
                   border-radius: 10px; padding: 16px 32px; margin-top: 16px; }}
    .score-num {{ font-size: 3rem; font-weight: 900; color: {gc}; text-shadow: none; }}
    .grade {{ font-size: 2rem; font-weight: 900; color: {gc}; }}

    /* ── Metric cards ── */
    .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; margin-bottom: 28px; }}
    .metric-card {{ background: white; border-radius: 10px; padding: 20px; text-align: center;
                    box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
    .metric-val {{ font-size: 1.8rem; font-weight: 800; }}
    .metric-label {{ font-size: 0.78rem; color: #64748b; margin-top: 4px; text-transform: uppercase; letter-spacing: .04em; }}

    /* ── Sections ── */
    .section {{ background: white; border-radius: 10px; padding: 24px; margin-bottom: 24px;
                box-shadow: 0 1px 4px rgba(0,0,0,.06); }}
    .section-title {{ font-size: 1.2rem; font-weight: 700; color: #1e3a5f; margin-bottom: 16px;
                      padding-bottom: 8px; border-bottom: 2px solid #e2e8f0; }}
    .section-label {{ font-size: 0.75rem; font-weight: 700; text-transform: uppercase;
                      letter-spacing: .06em; color: #64748b; margin-top: 10px; margin-bottom: 4px; }}

    /* ── Tables ── */
    table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    th {{ background: #1e3a5f; color: white; padding: 9px 12px; text-align: left; font-size: .82rem; }}
    td {{ padding: 8px 12px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }}
    tr:nth-child(even) td {{ background: #f8fafc; }}

    /* ── Rule cards ── */
    .rule-card {{ background: #f8fafc; border-radius: 8px; padding: 18px 20px;
                  margin-bottom: 16px; border-left: 4px solid #94a3b8; }}
    .rule-header {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }}
    .rule-id {{ font-size: 1rem; font-weight: 800; color: #0f172a; font-family: monospace; }}
    .badge {{ display: inline-block; padding: 2px 10px; border-radius: 9999px;
              font-size: 0.75rem; font-weight: 700; }}
    .violation-count {{ margin-left: auto; color: #64748b; font-size: 0.85rem; }}
    .rule-text {{ font-size: 0.85rem; color: #475569; margin-bottom: 8px; }}
    .steps-list {{ margin-left: 18px; font-size: 0.88rem; color: #374151; }}
    .steps-list li {{ margin-bottom: 4px; }}

    /* ── Utilities ── */
    .font-mono {{ font-family: monospace; }}
    .font-bold, .font-semibold {{ font-weight: 700; }}
    .text-center {{ text-align: center; }}
    .text-gray {{ color: #64748b; }}

    /* ── Footer ── */
    .footer {{ text-align: center; font-size: 0.8rem; color: #94a3b8; margin-top: 32px; padding: 16px; }}

    @media print {{
      body {{ background: white; }}
      .rule-card {{ break-inside: avoid; }}
    }}
  </style>
</head>
<body>
<div class="container">

  <!-- HEADER -->
  <div class="report-header">
    <h1>AML Compliance Scan Report</h1>
    <div class="subtitle">Anti-Money Laundering Data Compliance Audit</div>
    <div class="meta">Scan ID: {esc(scan_id)} &nbsp;|&nbsp; Generated: {esc(generated)} UTC</div>
    <div class="score-card">
      <div>
        <div class="score-num">{score:.1f}%</div>
        <div style="color:rgba(255,255,255,0.7); font-size:0.85rem">Compliance Score</div>
      </div>
      <div style="width:1px; height:60px; background:rgba(255,255,255,0.25)"></div>
      <div>
        <div class="grade">{esc(grade)}</div>
        <div style="color:rgba(255,255,255,0.7); font-size:0.85rem">Grade</div>
      </div>
    </div>
  </div>

  <!-- METRICS -->
  <div class="metrics-grid">
    <div class="metric-card">
      <div class="metric-val" style="color:#dc2626">{total_v:,}</div>
      <div class="metric-label">Total Violations</div>
    </div>
    <div class="metric-card">
      <div class="metric-val" style="color:#1e40af">{total_r}</div>
      <div class="metric-label">Rules Assessed</div>
    </div>
    <div class="metric-card">
      <div class="metric-val" style="color:#16a34a">{passing}</div>
      <div class="metric-label">Rules Passing</div>
    </div>
    <div class="metric-card">
      <div class="metric-val" style="color:#dc2626">{failing}</div>
      <div class="metric-label">Rules Failing</div>
    </div>
    <div class="metric-card">
      <div class="metric-val" style="color:#d97706">{nr_count:,}</div>
      <div class="metric-label">Needs Review</div>
    </div>
    <div class="metric-card">
      <div class="metric-val" style="color:#475569">{avg_conf:.2f}</div>
      <div class="metric-label">Avg Confidence</div>
    </div>
  </div>

  <!-- RULES SUMMARY TABLE -->
  <div class="section">
    <div class="section-title">Rules Summary</div>
    <table>
      <thead><tr>
        <th>Rule ID</th><th>Violations</th><th>Severity</th><th>Status</th><th>Rule Text</th>
      </tr></thead>
      <tbody>{rules_rows_html}</tbody>
    </table>
  </div>

  <!-- PER-RULE DETAIL -->
  <div class="section">
    <div class="section-title">Rule-by-Rule Detail</div>
    {rule_cards_html}
  </div>

  <!-- VIOLATIONS BY TABLE -->
  <div class="section">
    <div class="section-title">Appendix: Violations by Table</div>
    <table>
      <thead><tr><th>Table</th><th style="text-align:center">Violations</th></tr></thead>
      <tbody>{table_rows_html}</tbody>
    </table>
  </div>

  <div class="footer">
    Generated by Data Compliance Agent &nbsp;&middot;&nbsp; {esc(generated)} UTC &nbsp;&middot;&nbsp; Scan {esc(scan_id)}
  </div>
</div>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    log.info(f"HTML report written to {output_path}")
    return str(output_path)


# ═══════════════════════════════════════════════════════════════════════════════
#  Main entry point — called from run_hi_small step12
# ═══════════════════════════════════════════════════════════════════════════════

def generate_reports(
    state: Dict[str, Any],
    output_dir: str | Path = "data",
) -> Dict[str, str]:
    """
    Build both PDF and HTML reports from the pipeline state.

    Returns
    -------
    {"pdf": str, "html": str}  — absolute paths to output files.
    """
    output_dir = Path(output_dir)
    report           = state.get("violation_report", {})
    rule_explanations = state.get("rule_explanations", {})
    scan_id          = state.get("scan_id", report.get("scan_id", "scan"))

    # Sanitise scan_id for use in filename
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in scan_id)

    pdf_path  = output_dir / f"compliance_report_{safe_id}.pdf"
    html_path = output_dir / f"compliance_report_{safe_id}.html"

    pdf_out  = build_scan_report_pdf(report, rule_explanations, pdf_path)
    html_out = build_scan_report_html(report, rule_explanations, html_path)

    return {"pdf": pdf_out, "html": html_out}
