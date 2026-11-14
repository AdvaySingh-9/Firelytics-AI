"""SQLite schema + build (experiments, keywords, report text, FTS5 index)."""
import json
import sqlite3
from datetime import datetime, timezone

from . import config

SCHEMA = """
DROP TABLE IF EXISTS experiments;
DROP TABLE IF EXISTS experiment_keywords;
DROP TABLE IF EXISTS reports;
DROP TABLE IF EXISTS search_index;
DROP TABLE IF EXISTS meta;

CREATE TABLE experiments(
  study_id TEXT PRIMARY KEY, title TEXT, acronym TEXT, proposal_title TEXT,
  research_area TEXT, sub_research_area TEXT, project_type TEXT,
  objective TEXT, approach TEXT, hypothesis TEXT, research_impacts TEXT,
  hardware TEXT, hardware_link TEXT, flight_platform TEXT, managing_center TEXT,
  space_program TEXT, funding TEXT, doi TEXT, source_url TEXT,
  start_date TEXT, end_date TEXT, submitted_date TEXT, released_date TEXT,
  start_year INTEGER, end_year INTEGER,
  has_report INTEGER DEFAULT 0, report_pdf TEXT, report_text_path TEXT, report_chars INTEGER DEFAULT 0,
  keywords_json TEXT
);
CREATE TABLE experiment_keywords(study_id TEXT, keyword TEXT);
CREATE INDEX idx_kw ON experiment_keywords(study_id);
CREATE TABLE reports(study_id TEXT PRIMARY KEY, text TEXT, n_chars INTEGER);
CREATE VIRTUAL TABLE search_index USING fts5(
  study_id UNINDEXED, title, objective, approach, hypothesis, research_impacts, keywords, report,
  tokenize = 'porter unicode61'
);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
"""

EXP_COLS = ["study_id", "title", "acronym", "proposal_title", "research_area", "sub_research_area",
            "project_type", "objective", "approach", "hypothesis", "research_impacts", "hardware",
            "hardware_link", "flight_platform", "managing_center", "space_program", "funding", "doi", "source_url",
            "start_date", "end_date", "submitted_date", "released_date"]


def _year(d):
    return int(d[:4]) if d and d[:4].isdigit() else None


def build_db() -> int:
    src = config.CATALOG / "studies.json"
    if not src.exists():
        raise SystemExit("studies.json not found. Run: python -m psi_db catalog")
    studies = json.loads(src.read_text(encoding="utf-8"))
    config.DB_PATH.unlink(missing_ok=True)
    con = sqlite3.connect(config.DB_PATH)
    con.executescript(SCHEMA)
    seen = set()
    for s in studies:
        sid = s["study_id"]
        if sid in seen:                      # same Study Identifier in two folders: keep the first
            print(f"[build] WARNING duplicate study_id {sid}, skipped (check your raw folders)")
            continue
        seen.add(sid)
        txt_path = config.ROOT / s["report_text_path"] if s.get("report_text_path") else None
        report = txt_path.read_text(encoding="utf-8") if txt_path and txt_path.exists() else ""
        row = {c: s.get(c, "") for c in EXP_COLS}
        row.update(start_year=_year(s.get("start_date")), end_year=_year(s.get("end_date")),
                   has_report=1 if report.strip() else 0, report_pdf=s.get("report_pdf", ""),
                   report_text_path=s.get("report_text_path", ""), report_chars=len(report),
                   keywords_json=json.dumps(s.get("keywords", [])))
        cols = list(row)
        con.execute(f"INSERT OR REPLACE INTO experiments({','.join(cols)}) VALUES({','.join(':' + c for c in cols)})", row)
        for k in s.get("keywords", []):
            con.execute("INSERT INTO experiment_keywords VALUES(?,?)", (sid, k))
        if report.strip():
            con.execute("INSERT OR REPLACE INTO reports VALUES(?,?,?)", (sid, report, len(report)))
        title_field = " ".join(x for x in (s.get("title"), s.get("acronym"), s.get("proposal_title")) if x)
        con.execute("INSERT INTO search_index VALUES(?,?,?,?,?,?,?,?)",
                    (sid, title_field, s.get("objective", ""), s.get("approach", ""), s.get("hypothesis", ""),
                     s.get("research_impacts", ""), " ".join(s.get("keywords", [])), report))
    con.execute("INSERT INTO meta VALUES('built_at', ?)", (datetime.now(timezone.utc).isoformat(timespec="seconds"),))
    con.execute("INSERT INTO meta VALUES('experiment_count', ?)", (str(len(seen)),))
    con.commit()
    con.close()
    print(f"[build] {len(seen)} experiments -> {config.DB_PATH}")
    return len(seen)
