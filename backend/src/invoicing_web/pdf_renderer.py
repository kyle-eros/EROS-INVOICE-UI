from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import InvoicePdfContext, compute_split_amount

CENTS = Decimal("0.01")


def _format_date(value: date) -> str:
    return value.strftime("%m-%d-%Y")


def _format_currency(value: float | Decimal, currency: str) -> str:
    amount = Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)
    normalized_currency = currency.strip().upper() or "USD"
    if normalized_currency == "USD":
        return f"${amount:,.2f}"
    return f"{normalized_currency} {amount:,.2f}"


def _format_split_percent(value: float) -> str:
    decimal_value = Decimal(str(value))
    normalized = format(decimal_value.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return f"{normalized}%"


def render_invoice_pdf(invoice: InvoicePdfContext) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=f"Invoice {invoice.invoice_id}",
        author="EROS Invoicing",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "invoice_title",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        textColor=colors.HexColor("#111827"),
    )
    heading_style = ParagraphStyle(
        "invoice_heading",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#111827"),
        spaceAfter=3,
    )
    body_style = ParagraphStyle(
        "invoice_body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#111827"),
    )
    table_header_style = ParagraphStyle(
        "invoice_table_header",
        parent=body_style,
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=10,
    )
    table_cell_style = ParagraphStyle(
        "invoice_table_cell",
        parent=body_style,
        fontSize=8.5,
        leading=10,
    )
    table_numeric_style = ParagraphStyle(
        "invoice_table_numeric",
        parent=table_cell_style,
        alignment=TA_RIGHT,
    )
    thank_you_style = ParagraphStyle(
        "invoice_thank_you",
        parent=body_style,
        fontName="Helvetica-Bold",
        spaceBefore=12,
    )

    story: list = []
    story.append(Paragraph("INVOICE", title_style))
    story.append(Spacer(1, 0.12 * inch))

    header_rows = [
        ["Invoice #:", invoice.invoice_id],
        ["Date of Issue:", _format_date(invoice.issued_at)],
        ["Payment Due By:", _format_date(invoice.due_date)],
        ["Current Status:", invoice.status.replace("_", " ").title()],
    ]
    header_table = Table(header_rows, colWidths=[1.5 * inch, 5.5 * inch], hAlign="LEFT")
    header_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#111827")),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(header_table)
    story.append(Spacer(1, 0.14 * inch))

    story.append(Paragraph("Bill To:", heading_style))
    story.append(Paragraph(invoice.creator_name, body_style))
    story.append(Spacer(1, 0.14 * inch))

    story.append(Paragraph("Description", heading_style))
    story.append(Paragraph(invoice.detail.service_description, body_style))
    story.append(Spacer(1, 0.14 * inch))

    line_rows: list[list[object]] = [
        [
            Paragraph("Platform", table_header_style),
            Paragraph("Date Range", table_header_style),
            Paragraph("Line Item", table_header_style),
            Paragraph("Gross Total", table_header_style),
            Paragraph("Split (%)", table_header_style),
            Paragraph("Split Amount", table_header_style),
        ]
    ]
    for item in invoice.detail.line_items:
        split_amount = compute_split_amount(item.gross_total, item.split_percent)
        line_rows.append(
            [
                Paragraph(item.platform, table_cell_style),
                Paragraph(f"{_format_date(item.period_start)} to {_format_date(item.period_end)}", table_cell_style),
                Paragraph(item.line_label, table_cell_style),
                Paragraph(_format_currency(item.gross_total, invoice.currency), table_numeric_style),
                Paragraph(_format_split_percent(item.split_percent), table_numeric_style),
                Paragraph(_format_currency(split_amount, invoice.currency), table_numeric_style),
            ]
        )

    line_table = Table(
        line_rows,
        colWidths=[0.9 * inch, 1.5 * inch, 1.75 * inch, 0.9 * inch, 0.7 * inch, 1.25 * inch],
        repeatRows=1,
        hAlign="LEFT",
    )
    line_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#111827")),
                ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#d1d5db")),
                ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(line_table)
    story.append(Spacer(1, 0.16 * inch))

    total_table = Table(
        [
            ["Invoice Total", _format_currency(invoice.amount_due, invoice.currency)],
            ["Amount Paid", _format_currency(invoice.amount_paid, invoice.currency)],
            ["Balance Due", _format_currency(invoice.balance_due, invoice.currency)],
        ],
        colWidths=[5.25 * inch, 1.75 * inch],
        hAlign="LEFT",
    )
    total_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 11),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#111827")),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEABOVE", (0, 0), (-1, 0), 1, colors.HexColor("#9ca3af")),
                ("LINEABOVE", (0, 2), (-1, 2), 1, colors.HexColor("#6b7280")),
                ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
                ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#f9fafb")),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(total_table)
    story.append(Spacer(1, 0.16 * inch))

    story.append(Paragraph("Payment Method:", heading_style))
    story.append(Paragraph(invoice.detail.payment_method_label, body_style))
    story.append(Spacer(1, 0.08 * inch))

    payment_rows = [
        ["ZELLE Account Number:", invoice.detail.payment_instructions.zelle_account_number],
        ["Direct Deposit Account #:", invoice.detail.payment_instructions.direct_deposit_account_number],
        ["Direct Deposit Routing #:", invoice.detail.payment_instructions.direct_deposit_routing_number],
    ]
    payment_table = Table(payment_rows, colWidths=[2.4 * inch, 4.6 * inch], hAlign="LEFT")
    payment_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#111827")),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(payment_table)
    if invoice.balance_due > 0:
        story.append(
            Paragraph(
                f"Payment due by {_format_date(invoice.due_date)}.",
                body_style,
            )
        )
    story.append(Paragraph("Thank you for your business!", thank_you_style))

    doc.build(story)
    return buffer.getvalue()
