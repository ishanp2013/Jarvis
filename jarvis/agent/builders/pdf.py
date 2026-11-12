"""Text out of a PDF, for summaries and study notes."""
from pypdf import PdfReader


def text(path, max_chars=40000):
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise RuntimeError("That PDF is password-protected, so I can't read it.")
    out, total = [], 0
    for page in reader.pages:
        t = page.extract_text() or ""
        out.append(t)
        total += len(t)
        if total > max_chars:
            break
    joined = "\n".join(out).strip()
    if len(joined) < 50:
        raise RuntimeError("That PDF has no readable text (it may be scanned images).")
    return {"pages": len(reader.pages), "text": joined[:max_chars]}
