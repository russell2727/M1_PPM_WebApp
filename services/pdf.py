"""
Builds the branded PDF report with ReportLab + Matplotlib charts.
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle, KeepTogether)

import config

B = config.BRAND
NAVY = colors.HexColor(B["navy"])
BLUE = colors.HexColor(B["blue"])
TEAL = colors.HexColor(B["teal"])
GRAY = colors.HexColor(B["gray"])
LIGHT = colors.HexColor(B["light"])


def _fig_to_image(fig, width=6.5 * inch, height=3 * inch) -> Image:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight", transparent=True)
    plt.close(fig)
    buf.seek(0)
    return Image(buf, width=width, height=height)


def _chart_by_type(result: dict) -> Image:
    tc = result["by_type_condition"]
    types = list(tc.keys())
    conds = ["New", "Used"]
    fig, ax = plt.subplots(figsize=(8, 3.6))
    bottom = [0] * len(types)
    for i, c in enumerate(conds):
        vals = [tc[t].get(c, 0) for t in types]
        ax.bar(types, vals, bottom=bottom, label=c, color=B["chart"][i], width=0.6)
        bottom = [b + v for b, v in zip(bottom, vals)]
    for i, v in enumerate(bottom):
        ax.text(i, v, f"{v:,}", ha="center", va="bottom", fontsize=8, color=B["navy"])
    ax.set_ylabel("In-market shoppers")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False)
    ax.tick_params(axis="x", labelrotation=20)
    return _fig_to_image(fig, height=3.2 * inch)


def _chart_rings(result: dict) -> Image:
    rings = result["by_ring"]
    fig, ax = plt.subplots(figsize=(8, 2.6))
    ax.bar([f"{k} mi" for k in rings], list(rings.values()), color=B["teal"], width=0.55)
    for i, v in enumerate(rings.values()):
        ax.text(i, v, f"{v:,}", ha="center", va="bottom", fontsize=8, color=B["navy"])
    ax.set_ylabel("Shoppers")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax.set_xlabel("Distance from dealership")
    ax.spines[["top", "right"]].set_visible(False)
    return _fig_to_image(fig, height=2.4 * inch)


def build_pdf(result: dict, prospect: dict, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(out_path), pagesize=letter,
                            leftMargin=0.7 * inch, rightMargin=0.7 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.7 * inch,
                            title=f"In-Market Auto Shoppers - {prospect['dealership']}",
                            author=B["company"])
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=20, textColor=NAVY, alignment=TA_LEFT, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=ss["Normal"], fontSize=10.5, textColor=GRAY, spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=13, textColor=NAVY, spaceBefore=12, spaceAfter=6)
    body = ParagraphStyle("body", parent=ss["Normal"], fontSize=9.5, leading=13, textColor=colors.HexColor("#1F2937"))
    small = ParagraphStyle("small", parent=body, fontSize=8, textColor=GRAY)

    story = []

    # ---- header with logo
    logo = None
    if config.BRAND["logo_path"].exists():
        logo = Image(str(config.BRAND["logo_path"]), width=1.6 * inch, height=0.55 * inch, kind="proportional")
    header = Table([[logo or Paragraph(f"<b>{B['company']}</b>", h1),
                     Paragraph(f"<font size=8 color='{B['gray']}'>{B['tagline']}<br/>{B['website']}</font>", body)]],
                   colWidths=[3.5 * inch, 3.6 * inch])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
    story += [header, Spacer(1, 6)]
    rule = Table([[""]], colWidths=[7.1 * inch], rowHeights=[3])
    rule.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BLUE)]))
    story += [rule, Spacer(1, 12)]

    c = result["center"]
    conds = " & ".join(result["conditions"]) if result["conditions"] else "New & Used"
    story.append(Paragraph("In-Market Auto Shopper Report", h1))
    story.append(Paragraph(
        f"Prepared for <b>{prospect['name']}</b>, {prospect['dealership']} &nbsp;|&nbsp; "
        f"{c['city']}, {c['state']} {c['zip']} &nbsp;|&nbsp; {int(result['radius_mi'])}-mile radius &nbsp;|&nbsp; {conds} &nbsp;|&nbsp; "
        f"{datetime.now():%B %d, %Y}", sub))

    # ---- KPI tiles
    bc = result["by_condition"]
    kpis = [
        ("Total In-Market Shoppers", f"{result['total_shoppers']:,}"),
        ("New", f"{bc.get('New', 0):,}"),
        ("Used", f"{bc.get('Used', 0):,}"),
        ("ZIP Codes Covered", f"{result['zip_count']:,}"),
    ]
    tile_rows = [[Paragraph(f"<font size=18 color='{B['navy']}'><b>{v}</b></font><br/><font size=8 color='{B['gray']}'>{k}</font>", body) for k, v in kpis]]
    tiles = Table(tile_rows, colWidths=[1.775 * inch] * 4, rowHeights=[0.8 * inch])
    tiles.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story += [tiles, Spacer(1, 6)]

    # ---- charts
    story.append(Paragraph("Shoppers by Vehicle Type", h2))
    story.append(_chart_by_type(result))
    if result["by_ring"]:
        story.append(KeepTogether([Paragraph("Shoppers by Distance from Dealership", h2), _chart_rings(result)]))

    # ---- vehicle type table
    tot = max(result["total_shoppers"], 1)
    rows = [["Vehicle Type", "New", "Used", "Total", "% of Market"]]
    for t, d in result["by_type_condition"].items():
        n, u = d.get("New", 0), d.get("Used", 0)
        rows.append([t, f"{n:,}", f"{u:,}", f"{n + u:,}", f"{(n + u) / tot:.1%}"])
    rows.append(["Total", f"{bc.get('New', 0):,}", f"{bc.get('Used', 0):,}", f"{result['total_shoppers']:,}", "100%"])
    tbl = Table(rows, colWidths=[2.3 * inch, 1.2 * inch, 1.2 * inch, 1.2 * inch, 1.2 * inch])
    tbl.setStyle(_table_style(len(rows)))
    story.append(KeepTogether([Paragraph("Vehicle Type Breakdown", h2), tbl]))

    # ---- top zips
    rows = [["ZIP", "City", "State", "Miles", "Shoppers"]]
    for z in result["top_zips"][:20]:
        rows.append([z["zip"], str(z.get("city") or ""), str(z.get("state") or ""), f"{z['distance_mi']:.1f}", f"{int(z['shoppers']):,}"])
    tbl = Table(rows, colWidths=[0.9 * inch, 2.9 * inch, 0.8 * inch, 0.9 * inch, 1.6 * inch], repeatRows=1)
    tbl.setStyle(_table_style(len(rows), total_row=False))
    story.append(KeepTogether([Paragraph("Top ZIP Codes by Shopper Volume", h2), tbl]))

    story += [Spacer(1, 14), Paragraph(
        f"Source: {B['company']} Automotive File. In-market shoppers are consumers showing active purchase intent "
        f"signals within the selected radius and vehicle condition. Counts are de-duplicated at the household level. "
        f"Contact {B['company']} to activate this audience across email, SMS, direct mail, and programmatic channels.", small)]

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return out_path


def _table_style(n_rows: int, total_row: bool = True) -> TableStyle:
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if total_row:
        cmds += [("FONTNAME", (0, n_rows - 1), (-1, n_rows - 1), "Helvetica-Bold"),
                 ("LINEABOVE", (0, n_rows - 1), (-1, n_rows - 1), 1, NAVY)]
    return TableStyle(cmds)


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GRAY)
    canvas.drawString(0.7 * inch, 0.45 * inch, f"© {datetime.now().year} {B['company']}  |  Confidential — prepared for the named recipient")
    canvas.drawRightString(letter[0] - 0.7 * inch, 0.45 * inch, f"Page {doc.page}")
    canvas.restoreState()
