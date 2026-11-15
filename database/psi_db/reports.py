"""Pick the final-report PDF and extract its text."""

import json
import re
from pathlib import Path

from . import config


# fmt: off
def choose_report(candidates):
    """candidates: list of (name_or_key, size_bytes). Returns the best one or None.
    Prefers names containing REPORT_NAME_HINTS (more hints first, then smaller file).
    If nothing matches a hint, only a lone PDF is accepted (we never guess among many)."""
    if not candidates:
        return None

    def score(c):
        name = Path(c[0]).name.lower()
        return sum(h in name for h in config.REPORT_NAME_HINTS)

    hinted = [c for c in candidates if score(c) > 0]
    if hinted:
        return sorted(hinted, key=lambda c: (-score(c), c[1]))[0]
    return candidates[0] if len(candidates) == 1 else None


# fmt: on


def find_report_pdf(folder: Path):
    """Locate the report PDF inside data/raw/<id>/ (report.pdf first, else best match)."""
    pdfs = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf"]
    for p in pdfs:
        if p.name.lower() == "report.pdf":
            return p
    best = choose_report([(str(p), p.stat().st_size) for p in pdfs])
    return Path(best[0]) if best else None


def clean_text(t: str) -> str:
    t = t.replace("\r", "")
    t = re.sub(r"(\w)-\n(\w)", r"\1\2", t)  # join words hyphenated across lines
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def extract_pdf_text(pdf: Path):
    from pypdf import PdfReader

    reader = PdfReader(str(pdf))
    if reader.is_encrypted:
        reader.decrypt("")
    pages = [(p.extract_text() or "") for p in reader.pages]
    return clean_text("\n\n".join(pages)), len(pages)


def extract_all(force: bool = False) -> dict:
    config.ensure_dirs()
    status_path = config.REPORTS / "_status.json"
    status = json.loads(status_path.read_text()) if status_path.exists() else {}
    for folder in sorted(p for p in config.RAW.iterdir() if p.is_dir()):
        sid = folder.name
        out = config.REPORTS / f"{sid}.txt"
        pdf = find_report_pdf(folder)
        if pdf is None:
            status[sid] = {"status": "no_pdf"}
            print(f"[reports] {sid}: no PDF found")
            continue
        if out.exists() and not force:
            continue
        try:
            text, pages = extract_pdf_text(pdf)
            out.write_text(text, encoding="utf-8")
            ok = len(text) >= 50
            status[sid] = {
                "status": "ok" if ok else "no_text",
                "pages": pages,
                "chars": len(text),
                "pdf": pdf.name,
            }
            print(
                f"[reports] {sid}: {pages} pages, {len(text)} chars"
                + ("" if ok else "  (no text: scanned PDF?)")
            )
        except Exception as e:  # never kill the batch
            status[sid] = {"status": "error", "error": str(e)[:200]}
            print(f"[reports] {sid}: ERROR {e}")
    status_path.write_text(json.dumps(status, indent=2))
    return status
