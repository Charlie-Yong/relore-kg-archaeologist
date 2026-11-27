"""Render the maintained report source; requires ReportLab and a CJK font."""

import argparse
import re
from html import escape
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
pdfmetrics.registerFont(TTFont(
    "BodyCN", "/System/Library/Fonts/Supplemental/Songti.ttc", subfontIndex=6,
))
pdfmetrics.registerFont(TTFont(
    "HeadCN", "/System/Library/Fonts/STHeiti Medium.ttc", subfontIndex=0,
))
STYLES = {
    "title": ParagraphStyle("title", fontName="HeadCN", fontSize=20, leading=30,
                            textColor=HexColor("#163846"), spaceAfter=12, wordWrap="CJK"),
    "subtitle": ParagraphStyle("subtitle", fontName="HeadCN", fontSize=13, leading=20,
                               textColor=HexColor("#376271"), spaceAfter=12),
    "h1": ParagraphStyle("h1", fontName="HeadCN", fontSize=15, leading=23,
                         textColor=HexColor("#163846"), spaceBefore=16, spaceAfter=8,
                         keepWithNext=True),
    "h2": ParagraphStyle("h2", fontName="HeadCN", fontSize=11.8, leading=20,
                         textColor=HexColor("#376271"), spaceBefore=11, spaceAfter=5,
                         keepWithNext=True),
    "body": ParagraphStyle("body", fontName="BodyCN", fontSize=10.7, leading=18.1,
                           wordWrap="CJK", firstLineIndent=21.4, spaceAfter=7,
                           allowWidows=0, allowOrphans=0),
    "note": ParagraphStyle("note", fontName="HeadCN", fontSize=9.1, leading=15,
                           wordWrap="CJK", textColor=HexColor("#546772"), spaceAfter=10),
    "ref": ParagraphStyle("ref", fontName="BodyCN", fontSize=9.4, leading=14.5,
                          wordWrap="CJK", spaceAfter=5),
    "small": ParagraphStyle("small", fontName="HeadCN", fontSize=9, leading=15,
                            alignment=TA_CENTER, textColor=HexColor("#163846")),
    "table": ParagraphStyle("table", fontName="BodyCN", fontSize=8.2, leading=12.6,
                            wordWrap="CJK", textColor=HexColor("#243b44")),
    "table_head": ParagraphStyle("table_head", fontName="HeadCN", fontSize=8.4,
                                 leading=12.8, alignment=TA_CENTER, wordWrap="CJK",
                                 textColor=HexColor("#163846")),
}

URL_RE = re.compile(r"https?://[^\s，。；]+")
SEPARATOR_RE = re.compile(r"^\|(?:\s*:?-{3,}:?\s*\|)+$")


def page(canvas, doc, *, project="Flask"):
    canvas.saveState()
    canvas.setStrokeColor(HexColor("#c8d4d7"))
    canvas.setLineWidth(.5)
    canvas.line(56, 791, 539, 791)
    canvas.setFont("HeadCN", 8)
    canvas.setFillColor(HexColor("#57717a"))
    canvas.drawString(56, 802, f"开源项目历史知识图谱 · {project}")
    canvas.drawRightString(539, 802, "知识图谱课程 · 技术报告")
    canvas.line(56, 45, 539, 45)
    canvas.drawString(56, 31, "HistoryKG · 课程小组")
    canvas.drawRightString(539, 31, str(doc.page))
    canvas.restoreState()


def _bind_cjk_punctuation(html):
    # Preserve native ReportLab wordWrap="CJK" kinsoku behavior without splitting fragments.
    return html


def inline_markup(text):
    html = escape(text.replace("\u2013", "-")).replace("`", "")
    html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html)
    html = URL_RE.sub(
        lambda match: f'<link href="{match.group(0)}" color="#1f5f75">{match.group(0)}</link>',
        html,
    )
    return _bind_cjk_punctuation(html)


def _cell_display_len(text):
    clean = text.replace("**", "").replace("`", "")
    return sum(2 if ord(ch) > 127 else 1 for ch in clean)


def table_widths(rows, available=483):
    columns = len(rows[0])
    weights = []
    for index in range(columns):
        longest = max(_cell_display_len(row[index]) for row in rows)
        weights.append(max(12, min(longest + 4, 56)))
    total = sum(weights)
    widths = [available * weight / total for weight in weights]
    # Ensure narrow numeric ID / short label columns (e.g. 11-digit student IDs) don't wrap unnecessarily.
    for index in range(columns):
        header = rows[0][index].strip()
        if "学号" in header and widths[index] < 64:
            deficit = 64 - widths[index]
            widest = max(range(columns), key=lambda i: widths[i])
            if widest != index and widths[widest] - deficit > 140:
                widths[index] += deficit
                widths[widest] -= deficit
        elif ("互评" in header or "权重" in header) and widths[index] < 54:
            deficit = 54 - widths[index]
            widest = max(range(columns), key=lambda i: widths[i])
            if widest != index and widths[widest] - deficit > 140:
                widths[index] += deficit
                widths[widest] -= deficit
    return widths


def markdown_table(block):
    rows = []
    for line in block.splitlines():
        if not line.strip() or SEPARATOR_RE.fullmatch(line.strip()):
            continue
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    if not rows:
        return []
    columns = max(len(row) for row in rows)
    rows = [row + [""] * (columns - len(row)) for row in rows]
    data = [
        [
            Paragraph(inline_markup(cell or " "),
                      STYLES["table_head"] if row_index == 0 else STYLES["table"])
            for cell in row
        ]
        for row_index, row in enumerate(rows)
    ]
    table = Table(data, colWidths=table_widths(rows), repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#edf4f5")),
        ("GRID", (0, 0), (-1, -1), .4, HexColor("#bdcfd3")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return [KeepTogether([table, Spacer(1, 8)])]


def render(source, output, project):
    flow, pending_headings, references = [], [], False
    title = "开源项目历史知识图谱自动构建与可追溯问答"

    def emit(item):
        if pending_headings:
            if isinstance(item, KeepTogether):
                flow.append(KeepTogether([*pending_headings, *item._content]))
            else:
                flow.append(KeepTogether([*pending_headings, item]))
            pending_headings.clear()
        else:
            flow.append(item)

    for block in source.read_text(encoding="utf-8").strip().split("\n\n"):
        if block.strip() == "---":
            flow.append(Spacer(1, 4))
            continue
        if match := re.fullmatch(r"!\[([^\]]+)\]\((figures/[^()]+)\)", block):
            image_path = source.parent / match[2]
            image = Image(str(image_path))
            scale = min(483 / image.imageWidth, 330 / image.imageHeight)
            image.drawWidth, image.drawHeight = image.imageWidth * scale, image.imageHeight * scale
            emit(KeepTogether([
                image, Spacer(1, 5), Paragraph(inline_markup(match[1]), STYLES["small"]), Spacer(1, 12)
            ]))
            continue
        if references and all(re.match(r"(?:[-*]|\d+\.|\[\d+\]) ", line) for line in block.splitlines()):
            lines = [Paragraph(inline_markup(line), STYLES["ref"]) for line in block.splitlines()]
            emit(lines[0])
            flow.extend(lines[1:])
            continue
        if all(re.match(r"(?:[-*]|\d+\.) ", line) for line in block.splitlines()):
            lines = [Paragraph(inline_markup(line), STYLES["body"]) for line in block.splitlines()]
            emit(lines[0])
            flow.extend(lines[1:])
            continue
        if block.startswith("| "):
            items = markdown_table(block)
            if items:
                emit(items[0])
                flow.extend(items[1:])
            continue
        if block.startswith("# "):
            kind, text = "title", block[2:]
            title = text
        elif block.startswith("#### "):
            kind, text = "h2", block[5:]
        elif block.startswith("### "):
            kind, text = "h2", block[4:]
        elif block.startswith("## "):
            text = block[3:]
            kind = "subtitle" if text.startswith("以 ") else "h1"
            references = "参考文献" in text
        elif block.startswith("> "):
            text = " ".join(line.lstrip("> ").strip() for line in block.splitlines())
            kind = "note"
        else:
            text = block.replace("\n", " ")
            plain_prefix = re.sub(r"^\*\*(.+?)\*\*", r"\1", text)
            kind = "ref" if references else "note" if plain_prefix.startswith(
                ("2026年", "说明：", "关键词：", "关键词:", "隐私保护提示：", "课程实名提交确认：", "口径透明度说明：")
            ) else "body"
        html = inline_markup(text)
        para = Paragraph(html, STYLES[kind])
        if kind in ("h1", "h2"):
            pending_headings.append(para)
        else:
            emit(para)
        if text.startswith("真实Flask运行"):
            rows = [("公开来源", "369"), ("完整讨论", "40"), ("代码快照", "24"),
                    ("实体 / 关系", "133 / 183"), ("Decision", "61")]
            table = Table([[Paragraph(a, STYLES["small"]) for a, _ in rows],
                           [Paragraph(b, STYLES["small"]) for _, b in rows]], colWidths=[96.6]*5)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), HexColor("#edf4f5")),
                ("BOX", (0, 0), (-1, -1), .6, HexColor("#bdcfd3")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]))
            flow.extend([Spacer(1, 3), table, Spacer(1, 10)])
    if pending_headings:
        flow.extend(pending_headings)
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output), pagesize=A4, rightMargin=56, leftMargin=56, topMargin=66,
        bottomMargin=60, title=title, author="课程小组 P1-P6",
        subject="知识图谱课程技术报告", pageCompression=1,
    )
    def draw_page(canvas, document):
        page(canvas, document, project=project)
    doc.build(flow, onFirstPage=draw_page, onLaterPages=draw_page)
    print(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "reports/technical_report.md")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "output/pdf/historykg_technical_report.pdf")
    parser.add_argument("--project", default="Flask")
    args = parser.parse_args()
    render(args.source, args.output, args.project)


if __name__ == "__main__":
    main()
