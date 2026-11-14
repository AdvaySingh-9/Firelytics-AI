"""Parse a PSI ISA-Tab i_Investigation.txt into a clean flat dict."""
import csv
import io
from datetime import datetime
from pathlib import Path


def read_fields(path) -> dict:
    """Return {row name: [non-empty values]} for every row of the file."""
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    fields = {}
    for row in csv.reader(io.StringIO(text, newline=""), delimiter="\t", quotechar='"'):
        if not row or not any(c.strip() for c in row):
            continue
        key = row[0].strip()
        if len(row) == 1 and key.isupper():          # section header like STUDY
            continue
        fields[key] = [c.strip() for c in row[1:] if c.strip()]
    return fields


def _first(f, key):
    v = f.get(key, [])
    return v[0] if v else ""


def _joined(f, key):
    return " | ".join(f.get(key, []))


def norm_date(s: str) -> str:
    """'08-01-2007' / '31-Jul-2016' -> '2007-08-01'. Unknown formats are returned unchanged."""
    s = (s or "").strip()
    for fmt in ("%m-%d-%Y", "%d-%b-%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return s


def parse_investigation(path, fallback_id: str = "") -> dict:
    f = read_fields(path)
    keywords, seen = [], set()
    for k in f.get("Study Design Type", []):
        if k.lower() not in seen:
            seen.add(k.lower())
            keywords.append(k)
    return {
        "study_id": _first(f, "Study Identifier") or fallback_id,
        "title": _first(f, "Study Title"),
        "acronym": _first(f, "Comment[Investigation Acronym]"),
        "proposal_title": _first(f, "Comment[Proposal Title]"),
        "research_area": _first(f, "Comment[Research Area]"),
        "sub_research_area": _first(f, "Comment[SubResearch Area]"),
        "project_type": _first(f, "Comment[Project Type]"),
        "objective": _first(f, "Comment[Objective]"),
        "approach": _first(f, "Comment[Approach]"),
        "hypothesis": _first(f, "Comment[Hypothesis]"),
        "research_impacts": _first(f, "Comment[Research Impacts]"),
        "hardware": _joined(f, "Comment[Experiment Hardware]"),
        "hardware_link": _first(f, "Comment[Experiment Hardware Link]"),
        "flight_platform": _joined(f, "Comment[Flight Platform]"),
        "managing_center": _first(f, "Comment[Managing NASA Center]"),
        "space_program": _first(f, "Comment[Space Program]"),
        "funding": _first(f, "Comment[Funding]"),
        "doi": _first(f, "Comment[DOI]"),
        "start_date": norm_date(_first(f, "Comment[Investigation Start Date]")),
        "end_date": norm_date(_first(f, "Comment[Investigation End Date]")),
        "submitted_date": norm_date(_first(f, "Study Submission Date")),
        "released_date": norm_date(_first(f, "Study Public Release Date")),
        "keywords": keywords,
    }
