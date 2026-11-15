"""Search spec, query builder, experiment lookups and facets (SQLite FTS5)."""
import json
import re
import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FTS_COLUMNS = ("title", "objective", "approach", "hypothesis", "research_impacts", "keywords", "report")
TEXT_FILTERS = ("research_area", "sub_research_area", "project_type", "hardware",
                "flight_platform", "managing_center")
SORTS = ("relevance", "newest", "oldest", "title")

STOPWORDS = set("""a an the of in on at to for with and or but about as by from into over under is are was were be
been being do does did how what which who whom whose why when where can could would should will shall may might using uses used
me my we our you your i it its this that these those there their them they show find give tell list get
experiment experiments study studies research related relating regarding any all some""".split())


# ---------- search spec (the contract with the "search AI") ----------
def _as_list(v):
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    try:
        return [str(x) for x in v if str(x).strip()]
    except TypeError:
        return [str(v)]


def _opt_int(v):
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class Filters(BaseModel):
    model_config = ConfigDict(extra="ignore")
    research_area: list[str] = []
    sub_research_area: list[str] = []
    project_type: list[str] = []
    keywords: list[str] = []
    hardware: list[str] = []
    flight_platform: list[str] = []
    managing_center: list[str] = []
    has_report: bool | None = None
    start_year_min: int | None = None
    start_year_max: int | None = None

    @field_validator("research_area", "sub_research_area", "project_type", "keywords", "hardware",
                    "flight_platform", "managing_center", mode="before")
    @classmethod
    def _lists(cls, v):
        return _as_list(v)

    @field_validator("start_year_min", "start_year_max", mode="before")
    @classmethod
    def _years(cls, v):
        return _opt_int(v)

    @field_validator("has_report", mode="before")
    @classmethod
    def _bool(cls, v):
        return None if v in ("", None) else v


class SearchSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: str = ""
    search_in: list[str] = []
    filters: Filters = Field(default_factory=Filters)
    match: Literal["any", "all"] = "any"
    sort: Literal["relevance", "newest", "oldest", "title"] = "relevance"
    limit: int = 20
    offset: int = 0

    @field_validator("text", mode="before")
    @classmethod
    def _text(cls, v):
        return "" if v is None else str(v)

    @field_validator("search_in", mode="before")
    @classmethod
    def _search_in(cls, v):
        return [x.strip().lower() for x in _as_list(v) if x.strip().lower() in FTS_COLUMNS]

    @field_validator("filters", mode="before")
    @classmethod
    def _filters(cls, v):
        return {} if v is None else v

    @field_validator("match", mode="before")
    @classmethod
    def _match(cls, v):
        return v if v in ("any", "all") else "any"

    @field_validator("sort", mode="before")
    @classmethod
    def _sort(cls, v):
        return v if v in SORTS else "relevance"

    @field_validator("limit", mode="before")
    @classmethod
    def _limit(cls, v):
        n = _opt_int(v)
        return 20 if n is None else max(1, min(n, 100))

    @field_validator("offset", mode="before")
    @classmethod
    def _offset(cls, v):
        n = _opt_int(v)
        return 0 if n is None else max(0, n)


# ---------- query building ----------
def tokenize(text: str) -> list[str]:
    toks = re.findall(r"[A-Za-z0-9]+", (text or "").lower())
    seen, out = set(), []
    for t in toks:
        if t not in STOPWORDS and t not in seen and (len(t) > 1 or t.isdigit()):
            seen.add(t)
            out.append(t)
    return out


def _match_expr(tokens, mode, columns):
    body = (" OR " if mode == "any" else " ").join(f'"{t}"' for t in tokens)
    return f"{{{' '.join(columns)}}} : ({body})" if columns else body


def _like(v: str) -> str:
    return "%" + v.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _filter_sql(f: Filters):
    where, params = [], []
    for field in TEXT_FILTERS:
        vals = getattr(f, field)
        if vals:
            where.append("(" + " OR ".join(f"e.{field} LIKE ? ESCAPE '\\'" for _ in vals) + ")")
            params += [_like(v) for v in vals]
    if f.keywords:
        where.append("EXISTS (SELECT 1 FROM experiment_keywords k WHERE k.study_id = e.study_id AND ("
                     + " OR ".join("k.keyword LIKE ? ESCAPE '\\'" for _ in f.keywords) + "))")
        params += [_like(v) for v in f.keywords]
    if f.has_report is not None:
        where.append("e.has_report = ?")
        params.append(1 if f.has_report else 0)
    if f.start_year_min is not None:
        where.append("e.start_year >= ?")
        params.append(f.start_year_min)
    if f.start_year_max is not None:
        where.append("e.start_year <= ?")
        params.append(f.start_year_max)
    return where, params


CARD_COLS = ("e.study_id, e.title, e.acronym, e.research_area, e.sub_research_area, e.project_type, "
             "e.start_year, e.end_year, e.has_report, e.keywords_json")


def _card(row) -> dict:
    d = dict(row)
    d["keywords"] = json.loads(d.pop("keywords_json") or "[]")
    d["has_report"] = bool(d["has_report"])
    if d.get("score") is not None:
        d["score"] = round(d["score"], 6)
    return d


def search(con: sqlite3.Connection, spec: SearchSpec) -> dict:
    """Ranked search: best match first. Returns {total, limit, offset, results}."""
    con.row_factory = sqlite3.Row
    tokens = tokenize(spec.text)
    where, params = _filter_sql(spec.filters)
    if tokens:
        columns = spec.search_in or []
        from_sql = "search_index JOIN experiments e ON e.study_id = search_index.study_id"
        where = ["search_index MATCH ?"] + where
        params = [_match_expr(tokens, spec.match, columns)] + params
        # bm25 weights follow the FTS column order: study_id, title, objective, approach,
        # hypothesis, research_impacts, keywords, report
        select = (CARD_COLS + ", -bm25(search_index, 0, 8, 5, 3, 4, 3, 6, 1) AS score, "
                  "snippet(search_index, -1, '<mark>', '</mark>', '…', 24) AS snippet")
        relevance = "score DESC"
    else:
        from_sql = "experiments e"
        select = CARD_COLS + ", NULL AS score, '' AS snippet"
        relevance = "e.title COLLATE NOCASE"
    order = {"relevance": relevance, "newest": "e.start_date DESC", "oldest": "e.start_date ASC",
             "title": "e.title COLLATE NOCASE"}[spec.sort] + ", e.study_id"
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    total = con.execute(f"SELECT COUNT(*) FROM {from_sql}{where_sql}", params).fetchone()[0]
    rows = con.execute(f"SELECT {select} FROM {from_sql}{where_sql} ORDER BY {order} LIMIT ? OFFSET ?",
                       params + [spec.limit, spec.offset]).fetchall()
    return {"total": total, "limit": spec.limit, "offset": spec.offset, "results": [_card(r) for r in rows]}


# ---------- lookups ----------
def get_experiments(con: sqlite3.Connection, ids, include_report: bool = False) -> dict:
    """Full details for 1+ experiments, in the requested order. Unknown ids go to `missing`."""
    con.row_factory = sqlite3.Row
    found, missing = [], []
    for sid in ids:
        row = con.execute("SELECT * FROM experiments WHERE study_id = ? COLLATE NOCASE", (sid.strip(),)).fetchone()
        if row is None:
            missing.append(sid)
            continue
        d = dict(row)
        d["keywords"] = json.loads(d.pop("keywords_json") or "[]")
        d["has_report"] = bool(d["has_report"])
        if include_report:
            r = con.execute("SELECT text FROM reports WHERE study_id = ?", (d["study_id"],)).fetchone()
            d["report_text"] = r["text"] if r else ""
        found.append(d)
    return {"experiments": found, "missing": missing}


def facets(con: sqlite3.Connection) -> dict:
    """Distinct values + counts for each filter field (feed this to the search AI)."""
    con.row_factory = sqlite3.Row
    out = {}
    for field in TEXT_FILTERS:
        counts = {}
        for (v,) in con.execute(f"SELECT {field} FROM experiments WHERE {field} != ''"):
            for part in v.split(" | "):
                counts[part] = counts.get(part, 0) + 1
        out[field] = [{"value": k, "count": c} for k, c in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]
    out["keywords"] = [{"value": r[0], "count": r[1]} for r in con.execute(
        "SELECT keyword, COUNT(DISTINCT study_id) c FROM experiment_keywords GROUP BY keyword ORDER BY c DESC, keyword")]
    y = con.execute("SELECT MIN(start_year), MAX(start_year) FROM experiments").fetchone()
    out["start_year"] = {"min": y[0], "max": y[1]}
    t = con.execute("SELECT COUNT(*), COALESCE(SUM(has_report),0) FROM experiments").fetchone()
    out["totals"] = {"experiments": t[0], "with_report": t[1]}
    return out
