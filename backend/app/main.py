from collections import Counter
import csv, io, json
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from .data import INVESTIGATIONS
from .schemas import SearchRequest, CompareRequest, ExplainRequest, ChatRequest
from .search_service import list_catalogue, get_catalogue_record, natural_language_search

app = FastAPI(title="Firelytics AI API", version="0.2.0", description="API scaffold for the Firelytics AI NASA PSI research interface.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# TODO(database): replace this in-memory starter catalogue with repository/service calls.
# Do not treat the supplied inventory as a complete mirror of the NASA PSI repository.

def _inventory_lookup():
    return {item["study_id"].upper(): item for item in INVESTIGATIONS}

@app.get("/api/health")
def health():
    try:
        items = list_catalogue(_inventory_lookup())
        db_status = "connected"
        count = len(items)
    except Exception as exc:
        db_status = f"unavailable: {type(exc).__name__}"
        count = 0
    return {
        "status": "healthy",
        "service": "firelytics-ai-api",
        "database": db_status,
        "investigations_indexed": count,
        "search_llm": "groq" if __import__("os").getenv("GROQ_API_KEY") else "keyword_fallback",
        "search_model": __import__("os").getenv("GROQ_SEARCH_MODEL", "openai/gpt-oss-20b")
    }

@app.get("/api/investigations")
def list_investigations():
    try:
        items = list_catalogue(_inventory_lookup())
        return {"items": items, "total": len(items), "inventory_scope": "26 records in the supplied local PSI database; file categories are shown only where supplied"}
    except Exception:
        return {"items": INVESTIGATIONS, "total": len(INVESTIGATIONS), "inventory_scope": "11 team-supplied fallback records"}

@app.get("/api/investigations/{study_id}")
def get_investigation(study_id: str):
    try:
        item = get_catalogue_record(study_id, _inventory_lookup())
    except Exception:
        item = None
    if not item:
        item = next((x for x in INVESTIGATIONS if x["study_id"].lower() == study_id.lower()), None)
    if not item:
        raise HTTPException(404, "Investigation not found in the local catalogue")
    return item

@app.post("/api/search")
def search(payload: SearchRequest):
    try:
        return natural_language_search(payload.query, _inventory_lookup())
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        # Keep a usable lexical fallback if the AI/search integration has a transient issue.
        q = payload.query.lower()
        matches = [x for x in INVESTIGATIONS if q in " ".join([x["study_id"], x["title"], x["acronym"], x["summary"], x["objective"], " ".join(x["assets"])]).lower()]
        if "flex" in q:
            matches = list({x["study_id"]: x for x in matches + [INVESTIGATIONS[9]]}.values())
        return {"query": payload.query, "results": matches, "mode": "keyword_fallback", "warning": f"Database/AI search fallback: {type(exc).__name__}"}

@app.post("/api/explain")
def explain(payload: ExplainRequest):
    item = next((x for x in INVESTIGATIONS if x["study_id"] == payload.study_id), None)
    if not item:
        raise HTTPException(404, "Investigation not found")
    return {"mode": "metadata_only_explanation", "title": item["title"], "sections": [
        {"heading": "What is recorded", "body": item["summary"] + ". " + item["note"]},
        {"heading": "Research context", "body": item["objective"]},
        {"heading": "Evidence boundary", "body": "This response uses only catalogue metadata and asset categories currently stored by this starter API. It does not analyze un-ingested reports, raw measurements, or NASA documents."},
    ]}

@app.post("/api/compare")
def compare(payload: CompareRequest):
    found = [x for x in INVESTIGATIONS if x["study_id"] in payload.study_ids]
    if len(found) != len(set(payload.study_ids)):
        raise HTTPException(404, "One or more study IDs are not in the current catalogue")
    return {"mode": "catalogue_comparison", "items": found}

@app.get("/api/analytics")
def analytics():
    asset_counts = Counter(asset for item in INVESTIGATIONS for asset in item["assets"])
    return {"total": len(INVESTIGATIONS), "target_total": 26, "asset_counts": dict(asset_counts), "metadata_only": sum(not x["assets"] for x in INVESTIGATIONS), "scope": "team-supplied inventory"}

@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    """Temporary upload parser. Stores nothing; database/object storage is a future integration."""
    name = (file.filename or "").lower()
    raw = await file.read()
    try:
        if name.endswith(".json"):
            parsed = json.loads(raw.decode("utf-8-sig"))
            rows = parsed if isinstance(parsed, list) else parsed.get("items", parsed.get("data", [parsed]))
        elif name.endswith(".csv"):
            rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        else:
            raise HTTPException(415, "Only CSV and JSON files are supported")
    except (UnicodeDecodeError, json.JSONDecodeError, csv.Error) as exc:
        raise HTTPException(400, f"Could not parse uploaded file: {exc}")
    return {"filename": file.filename, "rows": len(rows), "preview": rows[:20], "stored": False, "message": "Parsed in memory only. Connect object storage/database to persist uploads."}

@app.post("/api/chat")
def chat(payload: ChatRequest):
    q = payload.message.lower()
    hits = [x for x in INVESTIGATIONS if q in (x["study_id"] + " " + x["title"] + " " + x["summary"] + " " + " ".join(x["assets"])).lower()]
    return {"mode": "starter_catalogue_assistant", "answer": (f"Matching records: {', '.join(x['study_id'] for x in hits)}. " + hits[0]["note"] if hits else "No direct match in the 11-record local catalogue. Connect an LLM and document-grounded RAG pipeline for deeper research questions."), "sources": [{"study_id": x["study_id"], "url": x["source_url"]} for x in hits]}
