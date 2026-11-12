"""Builds a finished Word document (reports, study notes, revision sheets, summaries)."""
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

NAVY, MUTED = RGBColor(0x1B, 0x2A, 0x41), RGBColor(0x6B, 0x72, 0x80)


def build(doc, path, images=None):
    """doc: {'title', 'subtitle', 'sections': [{'heading', 'paragraphs': [], 'bullets': [], 'table': {'columns', 'rows'}}],
    'sources': [{'title', 'url'}]}; images: {section index: {'path', 'credit'}}."""
    images = images or {}
    d = Document()
    st = d.styles["Normal"]
    st.font.name, st.font.size = "Calibri", Pt(11.5)
    for name, size in (("Title", 26), ("Heading 1", 16), ("Heading 2", 13)):
        d.styles[name].font.color.rgb = NAVY
        d.styles[name].font.size = Pt(size)
    d.add_heading(doc.get("title", "Document"), 0)
    if doc.get("subtitle"):
        p = d.add_paragraph(doc["subtitle"])
        p.runs[0].italic = True
        p.runs[0].font.color.rgb = MUTED
    for i, sec in enumerate(doc.get("sections", [])):
        if sec.get("heading"):
            d.add_heading(sec["heading"], 1)
        for para in sec.get("paragraphs", []):
            if str(para).strip():
                d.add_paragraph(str(para).strip())
        for b in sec.get("bullets", []):
            if str(b).strip():
                d.add_paragraph(str(b).strip(), style="List Bullet")
        t = sec.get("table")
        if t and t.get("columns") and t.get("rows"):
            table = d.add_table(rows=1, cols=len(t["columns"]))
            table.style = "Light Grid Accent 1"
            for c, name in enumerate(t["columns"]):
                table.rows[0].cells[c].text = str(name)
            for row in t["rows"][:40]:
                cells = table.add_row().cells
                for c, v in enumerate(row[:len(t["columns"])]):
                    cells[c].text = str(v)
        if img := images.get(i):
            d.add_picture(img["path"], width=Pt(380))
            d.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            cap = d.add_paragraph(img["credit"])
            cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            cap.runs[0].font.size, cap.runs[0].font.color.rgb = Pt(8), MUTED
    if doc.get("sources"):
        d.add_heading("Sources", 1)
        for s in doc["sources"]:
            d.add_paragraph(f"{s.get('title', '')}: {s.get('url', '')}", style="List Number")
    d.save(path)
    return len(doc.get("sections", []))


def check(path):
    d = Document(path)
    words = sum(len(p.text.split()) for p in d.paragraphs)
    return {"paragraphs": len(d.paragraphs), "words": words, "headings": sum(p.style.name.startswith("Heading") for p in d.paragraphs)}
