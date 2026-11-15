"""Parse every downloaded metadata file -> studies.csv + studies.json."""

import csv
import json

from . import config
from .isa_parser import parse_investigation
from .reports import find_report_pdf


def build_catalog() -> list:
    config.ensure_dirs()
    studies = []
    for folder in sorted(p for p in config.RAW.iterdir() if p.is_dir()):
        meta = next(
            (
                p
                for p in folder.rglob("*")
                if p.is_file() and p.name.lower() == config.METADATA_FILENAME.lower()
            ),
            None,
        )
        if meta is None:
            print(f"[catalog] {folder.name}: no {config.METADATA_FILENAME}, skipped")
            continue
        try:
            s = parse_investigation(meta, fallback_id=folder.name)
        except Exception as e:  # never kill the batch
            print(f"[catalog] {folder.name}: parse ERROR {e}")
            continue
        s["source_url"] = config.SOURCE_URL_TEMPLATE.format(
            study_id=s["study_id"].upper()
        )
        pdf = find_report_pdf(folder)
        txt = config.REPORTS / f"{folder.name}.txt"
        s["report_pdf"] = str(pdf.relative_to(config.ROOT)) if pdf else ""
        s["report_text_path"] = (
            str(txt.relative_to(config.ROOT)) if txt.exists() else ""
        )
        studies.append(s)

    (config.CATALOG / "studies.json").write_text(
        json.dumps(studies, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if studies:
        cols = list(studies[0].keys())
        with open(
            config.CATALOG / "studies.csv", "w", newline="", encoding="utf-8"
        ) as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for s in studies:
                w.writerow(
                    {
                        k: (", ".join(v) if isinstance(v, list) else v)
                        for k, v in s.items()
                    }
                )
    print(f"[catalog] {len(studies)} experiments -> {config.CATALOG}")
    return studies
