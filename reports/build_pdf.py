"""Render the maintained report source; requires ReportLab and a CJK font."""

from html import escape
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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
                           wordWrap="CJK", firstLineIndent=21.4, spaceAfter=7),
    "note": ParagraphStyle("note", fontName="HeadCN", fontSize=9.1, leading=15,
                           wordWrap="CJK", textColor=HexColor("#546772"), spaceAfter=10),
    "ref": ParagraphStyle("ref", fontName="BodyCN", fontSize=9.4, leading=15.5,
                          wordWrap="CJK", spaceAfter=7),
    "small": ParagraphStyle("small", fontName="HeadCN", fontSize=9, leading=15,
                            alignment=TA_CENTER, textColor=HexColor("#163846")),
}


def page(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(HexColor("#c8d4d7"))
    canvas.setLineWidth(.5)
    canvas.line(56, 791, 539, 791)
    canvas.setFont("HeadCN", 8)
    canvas.setFillColor(HexColor("#57717a"))
    canvas.drawString(56, 802, "开源项目历史知识图谱 · Flask")
    canvas.drawRightString(539, 802, "技术报告 / 阶段统稿 2026.10.30")
    canvas.line(56, 45, 539, 45)
    canvas.drawString(56, 31, "公开方法、工程结果与正式抽取统计；下游 A/B 待完成")
    canvas.drawRightString(539, 31, str(doc.page))
    canvas.restoreState()


def main():
    flow, references = [], False
    for block in (ROOT / "reports/technical_report.md").read_text().strip().split("\n\n"):
        if block.startswith("| "):
            rows = [[Paragraph(escape(cell.strip()), STYLES["small"])
                     for cell in line.strip().strip("|").split("|")]
                    for line in block.splitlines() if not line.startswith("| ---")]
            table = Table(rows, colWidths=[79, 92, 78, 78, 78, 78], repeatRows=1)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), HexColor("#edf4f5")),
                ("GRID", (0, 0), (-1, -1), .4, HexColor("#bdcfd3")),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]))
            flow.extend([table, Spacer(1, 10)])
            continue
        if block.startswith("# "):
            kind, text = "title", block[2:]
        elif block.startswith("### "):
            kind, text = "h2", block[4:]
        elif block.startswith("## "):
            text = block[3:]
            kind = "subtitle" if text.startswith("以 Flask") else "h1"
            if text == "参考文献":
                references = True
        else:
            text = block.replace("\n", " ")
            kind = "ref" if references else "note" if text.startswith(
                ("2026年", "说明：", "关键词：")
            ) else "body"
        html = escape(text)
        if kind == "title":
            html = "基于 relore 的开源项目历史知识图谱<br/>自动构建与可追溯问答"
        flow.append(Paragraph(html, STYLES[kind]))
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
    output = ROOT / "output/pdf/historykg_technical_report.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output), pagesize=A4, rightMargin=56, leftMargin=56, topMargin=66,
        bottomMargin=60, title="开源项目历史知识图谱自动构建与可追溯问答",
        author="课程小组 P1-P6", pageCompression=1,
    )
    doc.build(flow, onFirstPage=page, onLaterPages=page)
    print(output)


if __name__ == "__main__":
    main()
