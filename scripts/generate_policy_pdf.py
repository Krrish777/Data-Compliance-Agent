"""
Generate the AML (Anti-Money Laundering) Compliance Policy PDF
for the HI-Small Financial Transactions dataset.

Columns in scope:
  Timestamp, From Bank, Account, To Bank, Account_2,
  Amount Received, Receiving Currency, Amount Paid,
  Payment Currency, Payment Format, Is Laundering

Run:
    python scripts/generate_policy_pdf.py
"""
from __future__ import annotations

import os
import sys

# ── ensure project root is on sys.path when run directly ─────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUTPUT_PATH = os.path.join(ROOT, "data", "AML_Compliance_Policy.pdf")

# ── Style definitions ─────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

TITLE = ParagraphStyle(
    "Title",
    parent=styles["Title"],
    fontSize=22,
    spaceAfter=10,
    textColor=colors.HexColor("#1a237e"),
    alignment=TA_CENTER,
)
H1 = ParagraphStyle(
    "H1",
    parent=styles["Heading1"],
    fontSize=15,
    textColor=colors.HexColor("#1a237e"),
    spaceBefore=18,
    spaceAfter=6,
    borderPad=4,
)
H2 = ParagraphStyle(
    "H2",
    parent=styles["Heading2"],
    fontSize=12,
    textColor=colors.HexColor("#283593"),
    spaceBefore=12,
    spaceAfter=4,
)
BODY = ParagraphStyle(
    "Body",
    parent=styles["BodyText"],
    fontSize=10,
    spaceAfter=6,
    leading=14,
    alignment=TA_JUSTIFY,
)
RULE_BOX = ParagraphStyle(
    "RuleBox",
    parent=styles["BodyText"],
    fontSize=10,
    spaceAfter=4,
    leading=13,
    leftIndent=12,
    textColor=colors.HexColor("#1b5e20"),
)
NOTE = ParagraphStyle(
    "Note",
    parent=styles["BodyText"],
    fontSize=9,
    textColor=colors.HexColor("#555555"),
    leftIndent=12,
    spaceAfter=4,
    leading=12,
)

# ── Helper ────────────────────────────────────────────────────────────────────

def rule_table(rows: list[tuple[str, str]]) -> Table:
    """Render a 2-column table: Rule ID | Rule Text."""
    data = [["Rule ID", "Compliance Requirement"]] + list(rows)
    t = Table(data, colWidths=[3.2 * cm, 13.5 * cm])
    t.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a237e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8f9fa")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#e8eaf6")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c5cae9")),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    return t


# ── Document content ──────────────────────────────────────────────────────────

def build_pdf(output_path: str = OUTPUT_PATH) -> str:
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2 * cm,
        title="AML Compliance Policy — HI-Small Financial Transactions",
        author="Compliance Office",
    )

    story = []

    # ═══════════════════════════════════════════════════════════════════════════
    # COVER
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(Spacer(1, 3 * cm))
    story.append(Paragraph("Anti-Money Laundering (AML)", TITLE))
    story.append(Paragraph("Compliance Policy", TITLE))
    story.append(Paragraph("Financial Transaction Monitoring System", H2))
    story.append(Spacer(1, 0.5 * cm))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a237e")))
    story.append(Spacer(1, 0.5 * cm))

    meta = [
        ["Document Reference", "AML-POL-2024-001"],
        ["Version", "1.0"],
        ["Effective Date", "2024-01-01"],
        ["Review Date", "2025-01-01"],
        ["Classification", "Internal / Restricted"],
        ["Owner", "Chief Compliance Officer"],
        ["Dataset Scope", "HI-Small Financial Transactions (IBM Research)"],
    ]
    mt = Table(meta, colWidths=[5 * cm, 11 * cm])
    mt.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#9fa8da")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e8eaf6")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(mt)
    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 1 — PURPOSE
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("1. Purpose and Scope", H1))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#7986cb")))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        "This policy establishes the compliance requirements for monitoring financial "
        "transactions to detect potential money laundering activity. It applies to "
        "all transaction records processed by the organisation's payment systems, "
        "including bank transfers, credit card transactions, cheques, ACH payments, "
        "wire transfers, cash transactions, reinvestments, and cryptocurrency payments.",
        BODY,
    ))
    story.append(Paragraph(
        "All requirements in this document are mandatory. Non-compliance with these "
        "rules must be reported to the Compliance Office within 24 hours of detection. "
        "Automated systems SHALL flag all transactions that fail any rule defined herein "
        "for secondary review.",
        BODY,
    ))

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 2 — KEY DEFINITIONS
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("2. Key Definitions", H1))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#7986cb")))
    story.append(Spacer(1, 0.2 * cm))

    defs = [
        ("Large Transaction", "Any single transaction where the Amount Paid OR Amount Received exceeds 10,000 units of the primary currency (e.g. USD 10,000)."),
        ("Laundering Flag", "The binary field Is Laundering set to 1, indicating the transaction has been identified as potentially illicit."),
        ("Currency Mismatch", "A transaction where the Payment Currency differs from the Receiving Currency."),
        ("Cross-Bank Transfer", "A transaction where the From Bank code does not match the To Bank code."),
        ("High-Risk Payment Format", "Transactions using Bitcoin, Cash, or Wire formats, which carry elevated risk of obfuscation."),
        ("Self-Transfer", "A transaction where the originating Account (Account) and destination account (Account_2) are identical and originate from the same bank."),
        ("Micro-Transaction", "Any transaction where Amount Paid is less than 1.00 in any currency, potentially indicative of account probing."),
    ]

    for term, defn in defs:
        story.append(Paragraph(f"<b>{term}:</b> {defn}", RULE_BOX))

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 3 — DATA RETENTION
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("3. Data Retention Requirements", H1))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#7986cb")))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        "Transaction records must be retained in full for a minimum of 7 years from "
        "the date of the transaction. The Timestamp field must be populated for every "
        "record. Any transaction with a missing or null Timestamp is non-compliant and "
        "must be quarantined immediately.",
        BODY,
    ))
    story.append(rule_table([
        ("RET-001", "All transaction records shall retain the Timestamp field. Any record where Timestamp IS NULL or is an empty string is a data quality violation and must be quarantined."),
        ("RET-002", "All transaction records shall retain the Amount Paid field. Any record where Amount Paid IS NULL represents an incomplete entry and must be investigated."),
        ("RET-003", "All transaction records shall retain the Is Laundering field. Any record where Is Laundering IS NULL is a data integrity violation — the laundering assessment must be performed."),
    ]))

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 4 — TRANSACTION AMOUNT THRESHOLDS
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("4. Transaction Amount Thresholds", H1))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#7986cb")))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        "Transactions exceeding regulatory thresholds must be flagged for mandatory "
        "Suspicious Activity Report (SAR) filing. Under FinCEN requirements, any single "
        "cash transaction exceeding USD 10,000 requires a Currency Transaction Report "
        "(CTR). Institutions must also flag structuring — the practice of breaking large "
        "amounts into smaller transactions to avoid reporting. Any single transaction "
        "paid in cash exceeding $10,000 must be reported.",
        BODY,
    ))
    story.append(rule_table([
        ("AMT-001", "Any transaction where Amount Paid exceeds 10000 must be flagged for SAR/CTR review. The system SHALL identify all records where the numeric value of Amount Paid is greater than 10000."),
        ("AMT-002", "Any transaction where Amount Received exceeds 10000 must be flagged for SAR/CTR review. The system SHALL identify all records where the numeric value of Amount Received is greater than 10000."),
        ("AMT-003", "Micro-transactions: any transaction where Amount Paid is less than 1.00 must be flagged as a potential account-probing activity."),
        ("AMT-004", "All transactions where Amount Paid exceeds 1,000,000 (one million) in any currency shall trigger an enhanced due diligence review regardless of payment format."),
    ]))

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 5 — PAYMENT FORMAT CONTROLS
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("5. Payment Format Controls", H1))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#7986cb")))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        "The organisation processes transactions in the following permitted formats: "
        "ACH, Cheque, Credit Card, Reinvestment, Wire, Cash, and Bitcoin. "
        "Any transaction record where Payment Format does not contain one of these "
        "permitted values is non-compliant and must be rejected. "
        "Bitcoin and Cash payments carry elevated risk and require additional review.",
        BODY,
    ))
    story.append(rule_table([
        ("FMT-001", "The Payment Format field must not be NULL or empty. Any transaction record where Payment Format IS NULL is a data quality violation."),
        ("FMT-002", "Transactions using Bitcoin as the Payment Format shall be automatically flagged for enhanced due diligence. The system must identify all records where Payment Format equals 'Bitcoin'."),
        ("FMT-003", "Transactions using Cash as the Payment Format that also have an Amount Paid exceeding 10000 shall be flagged for mandatory CTR reporting."),
        ("FMT-004", "The Receiving Currency must not be NULL or empty. Any transaction where Receiving Currency IS NULL represents a data integrity failure."),
        ("FMT-005", "The Payment Currency must not be NULL or empty. Any transaction where Payment Currency IS NULL represents a data integrity failure."),
    ]))

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 6 — LAUNDERING DETECTION AND REPORTING
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("6. Laundering Detection and Reporting", H1))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#7986cb")))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        "Every transaction in the system carries a binary Is Laundering indicator. "
        "This field is set to 1 when the transaction has been identified as potentially "
        "illicit through the organisation's multi-agent simulation-based detection model "
        "(IBM Research, 2022). All flagged transactions must be reviewed by the compliance "
        "team within 48 hours. Automated reports must be generated daily for all "
        "transactions where Is Laundering equals 1.",
        BODY,
    ))
    story.append(rule_table([
        ("LAUN-001", "All transaction records where Is Laundering equals '1' must be flagged in the violations log for mandatory SAR filing. The system shall identify every record where Is Laundering = '1'."),
        ("LAUN-002", "The Is Laundering field must only contain values '0' or '1'. Any record where Is Laundering is neither '0' nor '1' (including NULL) represents a data integrity violation."),
        ("LAUN-003", "Transactions flagged as laundering (Is Laundering = '1') that use Bitcoin as the Payment Format represent extreme-risk events requiring immediate escalation to law enforcement liaison."),
    ]))

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 7 — ACCOUNT AND BANK CONTROLS
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("7. Account and Bank Controls", H1))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#7986cb")))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        "All transactions must have valid source and destination account identifiers. "
        "Missing account information prevents the transaction from being traced and "
        "constitutes a compliance failure. Self-transfers between the same account "
        "at the same bank must be monitored for potential layering activity.",
        BODY,
    ))
    story.append(rule_table([
        ("ACC-001", "The Account field (source account) must not be NULL or empty. Any transaction where Account IS NULL is a data quality violation."),
        ("ACC-002", "The Account_2 field (destination account) must not be NULL or empty. Any transaction where Account_2 IS NULL is a data quality violation."),
        ("ACC-003", "The From Bank field must not be NULL or empty. Any transaction where From Bank IS NULL is a data quality violation."),
        ("ACC-004", "The To Bank field must not be NULL or empty. Any transaction where To Bank IS NULL is a data quality violation."),
    ]))

    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 8 — ENFORCEMENT
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("8. Enforcement and Penalties", H1))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#7986cb")))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        "Violations of this policy may result in regulatory fines under the Bank Secrecy Act "
        "(BSA), FinCEN enforcement actions, or referral to federal law enforcement under "
        "18 U.S.C. § 1956 (money laundering statutes). Civil penalties can reach "
        "USD 25,000 per day per violation. Criminal penalties include imprisonment of "
        "up to 20 years per count.",
        BODY,
    ))

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 9 — RULE SUMMARY TABLE
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("9. Complete Rule Reference", H1))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#7986cb")))
    story.append(Spacer(1, 0.2 * cm))

    all_rules = [
        ("RET-001", "data_retention", "Timestamp IS NULL"),
        ("RET-002", "data_retention", "Amount Paid IS NULL"),
        ("RET-003", "data_retention", "Is Laundering IS NULL"),
        ("AMT-001", "data_quality",   "Amount Paid > 10000"),
        ("AMT-002", "data_quality",   "Amount Received > 10000"),
        ("AMT-003", "data_quality",   "Amount Paid < 1.00"),
        ("AMT-004", "data_quality",   "Amount Paid > 1000000"),
        ("FMT-001", "data_quality",   "Payment Format IS NULL"),
        ("FMT-002", "data_security",  "Payment Format = 'Bitcoin'"),
        ("FMT-003", "data_security",  "Payment Format = 'Cash' AND Amount Paid > 10000"),
        ("FMT-004", "data_quality",   "Receiving Currency IS NULL"),
        ("FMT-005", "data_quality",   "Payment Currency IS NULL"),
        ("LAUN-001","data_privacy",   "Is Laundering = '1'"),
        ("LAUN-002","data_quality",   "Is Laundering NOT IN ('0','1')"),
        ("LAUN-003","data_security",  "Is Laundering='1' AND Payment Format='Bitcoin'"),
        ("ACC-001", "data_quality",   "Account IS NULL"),
        ("ACC-002", "data_quality",   "Account_2 IS NULL"),
        ("ACC-003", "data_quality",   "From Bank IS NULL"),
        ("ACC-004", "data_quality",   "To Bank IS NULL"),
    ]

    summary = [["Rule ID", "Rule Type", "Testable SQL Condition"]] + [list(r) for r in all_rules]
    st = Table(summary, colWidths=[2.5 * cm, 3.5 * cm, 10.7 * cm])
    st.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a237e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#e8eaf6")]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c5cae9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(st)

    doc.build(story)
    print(f"[PDF] Written → {output_path}")
    return output_path


if __name__ == "__main__":
    build_pdf()
