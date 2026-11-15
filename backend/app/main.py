from collections import Counter
import csv, io, json
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from .data import INVESTIGATIONS
from .schemas import SearchRequest, CompareRequest, ExplainRequest, ChatRequest

app = FastAPI(
    title="Firelytics AI API",
    version="0.2.0",
    description="API scaffold for the Firelytics AI NASA PSI research interface.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# TODO(database): replace this in-memory starter catalogue with repository/service calls.
# Do not treat the supplied inventory as a complete mirror of the NASA PSI repository.


@app.get("/api/health")
def health():
    return {
        "status": "healthy",
        "service": "firelytics-ai-api",
        "database": "not_connected",
        "mode": "starter_catalogue",
    }


@app.get("/api/investigations")
def list_investigations():
    return {
        "items": INVESTIGATIONS,
        "total": len(INVESTIGATIONS),
        "inventory_scope": "11 team-supplied records; 26 target records",
    }


@app.get("/api/investigations/{study_id}")
def get_investigation(study_id: str):
    item = next(
        (x for x in INVESTIGATIONS if x["study_id"].lower() == study_id.lower()), None
    )
    if not item:
        raise HTTPException(
            404, "Investigation not found in the current local catalogue"
        )
    return item


@app.post("/api/search")
def search(payload: SearchRequest):
    q = payload.query.lower()
    matches = [
        x
        for x in INVESTIGATIONS
        if q
        in " ".join(
            [
                x["study_id"],
                x["title"],
                x["acronym"],
                x["summary"],
                x["objective"],
                " ".join(x["assets"]),
            ]
        ).lower()
    ]
    if "flex" in q:
        matches = list(
            {x["study_id"]: x for x in matches + [INVESTIGATIONS[9]]}.values()
        )
    return {
        "query": payload.query,
        "results": matches,
        "mode": "starter_keyword_search",
        "message": "Replace with semantic retrieval/RAG when the research index is ready.",
    }


@app.post("/api/explain")
def explain(payload: ExplainRequest):
    item = next((x for x in INVESTIGATIONS if x["study_id"] == payload.study_id), None)
    if not item:
        raise HTTPException(404, "Investigation not found")
    return {
        "mode": "metadata_only_explanation",
        "title": item["title"],
        "sections": [
            {
                "heading": "What is recorded",
                "body": item["summary"] + ". " + item["note"],
            },
            {"heading": "Research context", "body": item["objective"]},
            {
                "heading": "Evidence boundary",
                "body": "This response uses only catalogue metadata and asset categories currently stored by this starter API. It does not analyze un-ingested reports, raw measurements, or NASA documents.",
            },
        ],
    }


@app.post("/api/compare")
def compare(payload: CompareRequest):
    found = [x for x in INVESTIGATIONS if x["study_id"] in payload.study_ids]
    if len(found) != len(set(payload.study_ids)):
        raise HTTPException(
            404, "One or more study IDs are not in the current catalogue"
        )
    return {"mode": "catalogue_comparison", "items": found}


@app.get("/api/analytics")
def analytics():
    asset_counts = Counter(asset for item in INVESTIGATIONS for asset in item["assets"])
    return {
        "total": len(INVESTIGATIONS),
        "target_total": 26,
        "asset_counts": dict(asset_counts),
        "metadata_only": sum(not x["assets"] for x in INVESTIGATIONS),
        "scope": "team-supplied inventory",
    }


@app.get("/api/safety-insights")
def safety_insights():
    return {
        "mode": "research_themes_only",
        "insights": [
            {
                "theme": "Fire prevention",
                "description": "Research themes include flammability, fuel properties, oxygen concentration, and ignition conditions.",
                "evidence_status": "Requires source-document review",
            },
            {
                "theme": "Fire detection",
                "description": "Research themes include smoke, aerosol, and particle measurement.",
                "evidence_status": "Requires source-document review",
            },
            {
                "theme": "Fire suppression",
                "description": "Research themes include flame extinguishment and suppressant effectiveness.",
                "evidence_status": "PSI-69 metadata context available; quantitative evidence not yet ingested",
            },
        ],
    }


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    """Temporary upload parser. Stores nothing; database/object storage is a future integration."""
    name = (file.filename or "").lower()
    raw = await file.read()
    try:
        if name.endswith(".json"):
            parsed = json.loads(raw.decode("utf-8-sig"))
            rows = (
                parsed
                if isinstance(parsed, list)
                else parsed.get("items", parsed.get("data", [parsed]))
            )
        elif name.endswith(".csv"):
            rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        else:
            raise HTTPException(415, "Only CSV and JSON files are supported")
    except (UnicodeDecodeError, json.JSONDecodeError, csv.Error) as exc:
        raise HTTPException(400, f"Could not parse uploaded file: {exc}")
    return {
        "filename": file.filename,
        "rows": len(rows),
        "preview": rows[:20],
        "stored": False,
        "message": "Parsed in memory only. Connect object storage/database to persist uploads.",
    }


@app.post("/api/chat")
def chat(payload: ChatRequest):
    q = payload.message.lower()
    hits = [
        x
        for x in INVESTIGATIONS
        if q
        in (
            x["study_id"]
            + " "
            + x["title"]
            + " "
            + x["summary"]
            + " "
            + " ".join(x["assets"])
        ).lower()
    ]
    return {
        "mode": "starter_catalogue_assistant",
        "answer": (
            f"Matching records: {', '.join(x['study_id'] for x in hits)}. "
            + hits[0]["note"]
            if hits
            else "No direct match in the 11-record local catalogue. Connect an LLM and document-grounded RAG pipeline for deeper research questions."
        ),
        "sources": [{"study_id": x["study_id"], "url": x["source_url"]} for x in hits],
    }
