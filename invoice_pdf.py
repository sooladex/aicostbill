import io
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


def build_invoice_pdf(agency_name, invoice, client, items):
    """
    invoice: sqlite3.Row (invoices table)
    client: sqlite3.Row (clients table)
    items: list of sqlite3.Row (usage_entries)
    Returns: bytes of the PDF
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=20 * mm, bottomMargin=20 * mm,
        leftMargin=20 * mm, rightMargin=20 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleBig", parent=styles["Title"], fontSize=22, spaceAfter=2
    )
    small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=9, textColor=colors.grey)

    story = []
    story.append(Paragraph(agency_name, title_style))
    story.append(Paragraph("Facture d'usage IA", small))
    story.append(Spacer(1, 10 * mm))

    meta_table = Table(
        [
            ["Facture N°", f"INV-{invoice['id']:05d}"],
            ["Client", client["name"]],
            ["Periode", f"{invoice['period_start']} au {invoice['period_end']}"],
            ["Date d'emission", invoice["created_at"][:10]],
        ],
        colWidths=[45 * mm, 100 * mm],
    )
    meta_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 10 * mm))

    data = [["Date", "Projet", "Fournisseur", "Modele", "Description", "Cout (USD)"]]
    for it in items:
        data.append([
            it["entry_date"],
            it["project_name"],
            it["provider"],
            it["model"] or "-",
            (it["description"] or "")[:40],
            f"{it['cost_usd']:.2f}",
        ])

    item_table = Table(data, colWidths=[20*mm, 30*mm, 25*mm, 25*mm, 45*mm, 25*mm], repeatRows=1)
    item_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (5, 0), (5, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(item_table)
    story.append(Spacer(1, 8 * mm))

    totals_data = [
        ["Cout API total (sous-traite)", f"{invoice['subtotal_cost']:.2f} USD"],
        [f"Marge agence ({invoice['markup_pct']:.0f}%)",
         f"{(invoice['total_billed'] - invoice['subtotal_cost']):.2f} USD"],
        ["Total facture au client", f"{invoice['total_billed']:.2f} USD"],
    ]
    totals_table = Table(totals_data, colWidths=[100 * mm, 45 * mm])
    totals_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, 2), (-1, 2), 1, colors.black),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("FONTSIZE", (0, 2), (-1, 2), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 15 * mm))
    story.append(Paragraph(
        "Facture generee automatiquement a partir de la consommation d'API IA "
        "(OpenAI, Anthropic, autres) refacturee avec marge convenue.", small
    ))

    doc.build(story)
    return buf.getvalue()
