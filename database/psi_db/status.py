"""Coverage report: which experiments have metadata / a report PDF / extracted report text."""

import json

from . import config
from .reports import find_report_pdf


def coverage() -> list:
    if not config.RAW.exists():
        return []
    status_path = config.REPORTS / "_status.json"
    st = json.loads(status_path.read_text()) if status_path.exists() else {}
    rows = []
    for folder in sorted(
        (p for p in config.RAW.iterdir() if p.is_dir()), key=lambda p: p.name.lower()
    ):
        meta = any(
            p.is_file() and p.name.lower() == config.METADATA_FILENAME.lower()
            for p in folder.rglob("*")
        )
        pdf = find_report_pdf(folder)
        pdfs_total = sum(
            1 for p in folder.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf"
        )
        txt = config.REPORTS / f"{folder.name}.txt"
        chars = len(txt.read_text(encoding="utf-8")) if txt.exists() else 0
        if not meta:
            verdict = "NO METADATA"
        elif chars > 0:
            verdict = "full (metadata + report)"
        elif pdf is None and pdfs_total > 1:
            verdict = "metadata only - several PDFs, none picked (rename the report to report.pdf)"
        elif pdf is None:
            verdict = "metadata only - no report PDF"
        elif st.get(folder.name, {}).get("status") == "no_text":
            verdict = "metadata only - PDF has no text (scanned?)"
        else:
            verdict = "report PDF found - run: python -m psi_db reports"
        rows.append(
            {
                "id": folder.name,
                "metadata": meta,
                "pdf": bool(pdf),
                "report_chars": chars,
                "verdict": verdict,
            }
        )
    return rows


def print_coverage():
    rows = coverage()
    if not rows:
        print(f"No experiment folders found. Expected them in: {config.RAW}")
        return
    w = max(len(r["id"]) for r in rows)
    for r in rows:
        print(
            f"{r['id']:<{w}}  meta={'Y' if r['metadata'] else 'N'}  pdf={'Y' if r['pdf'] else 'N'}  "
            f"chars={r['report_chars']:<7} {r['verdict']}"
        )
    full = sum(r["report_chars"] > 0 for r in rows)
    print(
        f"\n{len(rows)} experiments: {full} with report text, {len(rows) - full} metadata-only"
    )
