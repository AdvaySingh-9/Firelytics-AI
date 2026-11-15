"""FastAPI app: search + experiment lookups. Run: python -m psi_db serve  (docs at /docs)."""

import sqlite3
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import config
from .search import SearchSpec, facets, get_experiments, search

app = FastAPI(title="PSI Combustion Experiments DB", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


def db():
    if not config.DB_PATH.exists():
        raise HTTPException(503, "Database not built yet. Run: python -m psi_db build")
    con = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


SECTION_FIELDS = [
    ("objective", "Objective"),
    ("hypothesis", "Hypothesis"),
    ("approach", "Approach"),
    ("research_impacts", "Research impacts"),
]
FACT_FIELDS = [
    ("research_area", "Research area"),
    ("sub_research_area", "Sub-research area"),
    ("project_type", "Project type"),
    ("hardware", "Hardware"),
    ("flight_platform", "Flight platform"),
    ("managing_center", "Managing NASA center"),
    ("start_date", "Start date"),
    ("end_date", "End date"),
]


def _decorate(exp: dict) -> dict:
    """Add the fields the UI/AI need: source link, attribution, limited-info notice, display layout."""
    sid = exp["study_id"].upper()
    exp["report_url"] = (
        f"/experiments/{exp['study_id']}/report.pdf" if exp.get("report_pdf") else None
    )
    exp["source_url"] = exp.get("source_url") or config.SOURCE_URL_TEMPLATE.format(
        study_id=sid
    )
    exp["source_attribution"] = config.SOURCE_ATTRIBUTION
    exp["limited_info"] = not exp["has_report"]
    exp["limited_info_message"] = (
        None if exp["has_report"] else config.LIMITED_INFO_MESSAGE
    )
    exp["sections"] = [
        {"key": k, "label": lbl, "text": exp[k]}
        for k, lbl in SECTION_FIELDS
        if exp.get(k)
    ]
    exp["facts"] = [
        {"key": k, "label": lbl, "value": exp[k]}
        for k, lbl in FACT_FIELDS
        if exp.get(k)
    ]
    return exp


@app.get("/health")
def health(con=Depends(db)):
    meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
    return {
        "status": "ok",
        "experiments": int(meta.get("experiment_count", 0)),
        "built_at": meta.get("built_at"),
    }


@app.get("/facets")
def get_facets(con=Depends(db)):
    return facets(con)


@app.get("/search/spec-schema")
def spec_schema():
    return SearchSpec.model_json_schema()


@app.get("/search")
def simple_search(q: str = "", limit: int = 20, offset: int = 0, con=Depends(db)):
    return search(con, SearchSpec(text=q, limit=limit, offset=offset))


@app.post("/search")
def structured_search(spec: SearchSpec, con=Depends(db)):
    return search(con, spec)


@app.get("/experiments")
def experiments(
    ids: Optional[str] = Query(None, description="comma-separated, e.g. PSI-69,PSI-70"),
    include_report: bool = False,
    limit: int = 50,
    offset: int = 0,
    con=Depends(db),
):
    if not ids:  # browse mode: cards for all experiments
        return search(con, SearchSpec(sort="title", limit=limit, offset=offset))
    id_list = [i for i in ids.split(",") if i.strip()]
    if len(id_list) > 10:
        raise HTTPException(400, "Maximum 10 ids per request")
    res = get_experiments(con, id_list, include_report)
    res["experiments"] = [_decorate(e) for e in res["experiments"]]
    return res


@app.get("/experiments/{study_id}")
def one_experiment(study_id: str, include_report: bool = False, con=Depends(db)):
    res = get_experiments(con, [study_id], include_report)
    if not res["experiments"]:
        raise HTTPException(404, f"{study_id} not found")
    return _decorate(res["experiments"][0])


@app.get("/experiments/{study_id}/report")
def report_text(study_id: str, con=Depends(db)):
    res = get_experiments(con, [study_id], include_report=True)
    if not res["experiments"]:
        raise HTTPException(404, f"{study_id} not found")
    e = res["experiments"][0]
    if not e["report_text"]:
        raise HTTPException(404, f"No report text for {e['study_id']}")
    return {"study_id": e["study_id"], "text": e["report_text"]}


@app.get("/experiments/{study_id}/report.pdf")
def report_pdf(study_id: str, con=Depends(db)):
    res = get_experiments(con, [study_id])
    if not res["experiments"] or not res["experiments"][0]["report_pdf"]:
        raise HTTPException(404, "No report PDF")
    path = config.ROOT / res["experiments"][0]["report_pdf"]
    if not path.exists():
        raise HTTPException(404, "PDF file missing on disk")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"{res['experiments'][0]['study_id']}-report.pdf",
    )
