from collections import Counter
import asyncio
import csv, io, json, tempfile, os
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from .data import INVESTIGATIONS
from .schemas import SearchRequest, CompareRequest, ExplainRequest, ChatRequest, SessionCreateRequest, SessionQuestionRequest, SessionDatasetRequest, SessionIngestRequest, SessionDirectDownloadRequest
from .search_service import list_catalogue, get_catalogue_record, natural_language_search
from .session_service import create_session, get_session, session_summary, delete_session, cleanup_expired_sessions, explore_session_datasets, ingest_session_batch, fetch_deferred_assets, _asset_uid, _extract_file
from .psi_discovery import is_allowed_psi_file_url, _category
import urllib.parse, re
from .analysis_service import answer_from_session, analyze_uploaded_dataset, _groq_client

app = FastAPI(title="Firelytics AI API", version="0.3.0", description="NASA PSI research interface with temporary investigation sessions and evidence-grounded analysis.")
_cors_origins = [x.strip() for x in os.getenv("FIRELYTICS_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

async def _session_cleanup_loop():
    while True:
        await asyncio.sleep(60)
        cleanup_expired_sessions()

@app.on_event("startup")
async def startup_cleanup():
    cleanup_expired_sessions()
    app.state.session_cleanup_task = asyncio.create_task(_session_cleanup_loop())

@app.on_event("shutdown")
async def shutdown_cleanup():
    task = getattr(app.state, "session_cleanup_task", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

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
        "search_model": __import__("os").getenv("GROQ_SEARCH_MODEL", "openai/gpt-oss-20b"),
        "analysis_llm": "groq" if __import__("os").getenv("GROQ_API_KEY") else "evidence_preview_fallback",
        "analysis_model": __import__("os").getenv("GROQ_DEEP_ANALYSIS_MODEL", "openai/gpt-oss-120b"),
        "session_workspace": "temporary_with_ttl_cleanup"
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

@app.post("/api/sessions")
def start_investigation_session(payload: SessionCreateRequest):
    """Prepare a temporary workspace for a selected investigation."""
    try:
        return create_session(payload.study_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Could not prepare investigation session: {type(exc).__name__}: {exc}")

@app.get("/api/sessions/{session_id}")
def read_investigation_session(session_id: str):
    data = get_session(session_id)
    if not data:
        raise HTTPException(404, "Investigation session expired or not found")
    return session_summary(data)

@app.post("/api/sessions/{session_id}/ingest")
def ingest_investigation_session(session_id: str, payload: SessionIngestRequest):
    raise HTTPException(410, "Automatic NASA downloads and extraction are disabled. Open the official PSI record and upload a file manually if needed.")


@app.post("/api/sessions/{session_id}/download-url")
def ingest_direct_psi_download(session_id: str, payload: SessionDirectDownloadRequest):
    raise HTTPException(410, "Automatic NASA downloads and extraction are disabled. Open the official PSI record and upload a file manually if needed.")

@app.get("/api/sessions/{session_id}/files/{asset_id}")
def download_session_asset(session_id: str, asset_id: str):
    raise HTTPException(410, "Files are not downloaded or stored by Firelytics. Open the official PSI record.")
@app.post("/api/sessions/{session_id}/analyze")
def analyze_investigation_session(session_id: str, payload: SessionQuestionRequest):
    data = get_session(session_id)
    if not data:
        raise HTTPException(404, "Investigation session expired or not found. Select the investigation again.")
    return answer_from_session(payload.question, data, payload.history, payload.uploaded_data)


@app.post("/api/sessions/{session_id}/datasets")
def explore_investigation_datasets(session_id: str, payload: SessionDatasetRequest):
    data = get_session(session_id)
    if not data:
        raise HTTPException(404, "Investigation session expired or not found. Select the investigation again.")
    try:
        return analyze_uploaded_dataset(data, payload.question, payload.uploaded_data)
    except Exception as exc:
        raise HTTPException(502, f"Uploaded dataset analysis failed: {type(exc).__name__}: {exc}")

@app.delete("/api/sessions/{session_id}")
def end_investigation_session(session_id: str):
    deleted = delete_session(session_id)
    return {"deleted": deleted, "session_id": session_id}

@app.post("/api/explain")
def explain(payload: ExplainRequest):
    # Explanations are generated from the complete structured PSI investigation
    # metadata, not from the shortened card summary or file inventory.
    item = get_catalogue_record(payload.study_id, {})
    if not item:
        item = next((x for x in INVESTIGATIONS if x["study_id"].casefold() == payload.study_id.casefold()), None)
    if not item:
        raise HTTPException(404, "Investigation not found")
    fields = ("study_id", "title", "acronym", "proposal_title", "objective", "approach", "hypothesis",
              "research_impacts", "research_area", "sub_research_area", "project_type", "hardware",
              "flight_platform", "managing_center", "space_program", "start_date", "end_date", "keywords")
    metadata = {k: item.get(k) for k in fields if item.get(k) not in (None, "", [])}
    uploaded_context = []
    if payload.uploaded_data:
        upload_session = get_session(payload.session_id) if payload.session_id else None
        if not upload_session or str(upload_session.get("study_id", "")).casefold() != payload.study_id.casefold():
            raise HTTPException(409, "Uploaded evidence is not attached to the active session for this investigation.")
        matching_uploads = [
            upload for upload in payload.uploaded_data
            if isinstance(upload, dict)
            and str(upload.get("__study_id__", "")).casefold() == payload.study_id.casefold()
            and str(upload.get("__session_id__", "")) == str(payload.session_id)
        ]
        if not matching_uploads:
            raise HTTPException(409, "The uploaded file is not bound to this investigation session and was not used.")
        uploaded_context = [
            {
                "filename": upload.get("__filename__"),
                "extracted_text": str(upload.get("__file_text__", ""))[:100000],
                "columns": upload.get("__columns__", [])[:200],
                "row_count": upload.get("__row_count__"),
                "numeric_summary": upload.get("__numeric_summary__", {}),
                "sheets": upload.get("__sheets__", [])[:20],
                "preview_rows": upload.get("__preview_rows__", [])[:100],
            }
            for upload in matching_uploads
        ]
    try:
        client = _groq_client()
        if not client:
            raise RuntimeError("GROQ_API_KEY is not configured")
        response = client.chat.completions.create(
            model=__import__("os").getenv("GROQ_DEEP_ANALYSIS_MODEL", "openai/gpt-oss-120b"),
            messages=[
                {"role": "system", "content": "You are Firelytics AI, using the 120B deep-analysis model. Write a polished, readable scientific explanation for a human researcher, not a dump of database fields. Synthesize all available metadata that materially helps explain this investigation: objectives, approach/methodology, hypotheses, research impacts/Earth benefits, research area, project type, hardware, flight platform, managing center, keywords and relevant dates. Organize the response into concise, meaningful sections only where the source contains information. Explain what the study is trying to establish, how the experiment is conducted, what hypotheses are being tested, why the work matters, and how the components relate. Use clear language while preserving technical terms and important specifics. Do not repeat the objective in other sections. Do not display DOI values, funding codes, raw database keys, raw JSON, inventory status or irrelevant administrative metadata. If uploaded file evidence is supplied in the user payload, analyze that evidence and cite its filename; otherwise do not claim to have inspected any source file. When no uploaded file is supplied, begin with the concise notice: 'Basis: recorded PSI metadata (no source file was used).' If the user asks for experimental results, measurements, safety findings, or another detail absent from metadata, state that it is not available in the metadata and ask the user to upload the relevant PSI report or experimental file. Do not invent findings, results, measurements, or facts absent from the supplied metadata or uploaded evidence. Distinguish recorded facts from your interpretation. If a scientifically relevant field is absent, mention that limitation briefly rather than filling it with generic knowledge. Output clean Markdown with headings and readable paragraphs; no decorative icons or meta-commentary."},
                {"role": "user", "content": json.dumps({"task": "Explain this NASA PSI investigation comprehensively. Incorporate uploaded file evidence where relevant and clearly distinguish recorded metadata from file-derived evidence and interpretation.", "metadata": metadata, "uploaded_files_for_this_investigation_only": uploaded_context}, ensure_ascii=False, default=str)}
            ], temperature=0.15, max_completion_tokens=1800,
            reasoning_effort=__import__("os").getenv("GROQ_ANALYSIS_REASONING_EFFORT", "medium"))
        answer = response.choices[0].message.content or "The language model returned an empty explanation."
        mode = "groq_metadata_deep_analysis"
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("120B metadata explanation failed for %s", payload.study_id)
        raise HTTPException(
            503,
            "The 120B deep-analysis model could not generate this explanation. Check GROQ_API_KEY and GROQ_DEEP_ANALYSIS_MODEL, then retry. No raw metadata dump is being presented as an AI answer."
        ) from exc
    mode = "groq_120b_metadata_and_file_analysis" if uploaded_context else "groq_120b_metadata_deep_analysis"
    return {"mode": mode, "title": item.get("title"), "metadata": metadata,
            "sections": [{"heading": "AI-assisted interpretation", "body": answer}], "answer_basis": "file" if uploaded_context else "metadata", "sources": []}

@app.post("/api/compare")
def compare(payload: CompareRequest):
    if payload.uploaded_data:
        if not payload.upload_study_id or payload.upload_study_id.casefold() not in {x.casefold() for x in payload.study_ids}:
            raise HTTPException(409, "The uploaded file's investigation must be included in the comparison selection.")
        if not any(
            isinstance(upload, dict)
            and str(upload.get("__study_id__", "")).casefold() == payload.upload_study_id.casefold()
            for upload in payload.uploaded_data
        ):
            raise HTTPException(409, "The uploaded file belongs to a different investigation and was not used in this comparison.")
    found = []
    for study_id in dict.fromkeys(payload.study_ids):
        try:
            item = get_catalogue_record(study_id, _inventory_lookup())
        except Exception:
            item = None
        if not item:
            item = next((x for x in INVESTIGATIONS if x["study_id"].casefold() == study_id.casefold()), None)
        if not item:
            raise HTTPException(404, f"Investigation {study_id} is not in the current catalogue")
        matching_uploads = [
            upload for upload in payload.uploaded_data
            if isinstance(upload, dict)
            and payload.upload_study_id
            and item["study_id"].casefold() == payload.upload_study_id.casefold()
            and str(upload.get("__study_id__", "")).casefold() == item["study_id"].casefold()
        ]
        if matching_uploads:
            item = dict(item)
            upload = matching_uploads[0]
            item["user_uploaded_experiment_data"] = {
                "source": "User upload",
                "filename": upload.get("__filename__", "User-uploaded experiment file"),
                "rows_supplied": upload.get("__row_count__", len(upload.get("__preview_rows__", []))),
                "columns": upload.get("__columns__", list(upload.keys()))[:100],
                "extracted_content": str(upload.get("__file_text__", ""))[:18000],
                "numeric_summary": upload.get("__numeric_summary__", {}),
                "sheets": upload.get("__sheets__", [])[:10],
                "sample_rows": upload.get("__preview_rows__", payload.uploaded_data[:10])[:10],
                "note": "This is user-supplied extracted experimental evidence, not a NASA repository inventory entry."
            }
        found.append(item)
    # Compare scientific content, not whether files happen to be listed.
    comparison_fields = ("title", "objective", "approach", "hypothesis", "research_impacts", "research_area", "sub_research_area", "project_type", "hardware", "flight_platform", "managing_center", "keywords")
    comparison_metadata = [{k: item.get(k) for k in comparison_fields if item.get(k) not in (None, "", [])} | {"study_id": item["study_id"]} for item in found]
    comparison_analysis = None
    comparison_mode = "metadata_comparison_fallback"
    try:
        client = _groq_client()
        if not client:
            raise RuntimeError("GROQ_API_KEY is not configured")
        response = client.chat.completions.create(
            model=__import__("os").getenv("GROQ_DEEP_ANALYSIS_MODEL", "openai/gpt-oss-120b"),
            messages=[
                {"role": "system", "content": "You are Firelytics AI using the 120B deep-analysis model. Write a concise, decision-useful scientific comparison, not a field-by-field dump. Maximum 450 words. Use exactly: (1) a 1-2 sentence overall takeaway; (2) 3-4 short bullets covering the most meaningful similarities and differences in purpose, approach, hypotheses, apparatus/platform or impact; (3) a brief 'What cannot be compared' note. Mention only differences that matter. Do not restate every field or repeat study titles. Do not compare file availability, inventory, DOI, funding codes or administrative identifiers. An uploaded file belongs ONLY to its explicitly attached study; never transfer its measurements to another study. Interpret actual extracted contents, columns and units only when supplied. Do not claim numerical cross-study results unless comparable measured data from both studies are supplied. Clearly distinguish metadata-based interpretation from file-derived observations. If no file evidence is used, begin with 'Basis: recorded PSI metadata (no source file was used).' If a file is used, identify its filename naturally. If evidence is missing, say so briefly. No raw metadata or JSON."},
                {"role": "user", "content": json.dumps({"investigations": comparison_metadata, "user_uploaded_experiment_data": [{"study_id": x["study_id"], "data": x.get("user_uploaded_experiment_data")} for x in found if x.get("user_uploaded_experiment_data")]}, ensure_ascii=False, default=str)}
            ], temperature=0.15, max_completion_tokens=1000,
            reasoning_effort=__import__("os").getenv("GROQ_ANALYSIS_REASONING_EFFORT", "medium"))
        comparison_analysis = response.choices[0].message.content or None
        comparison_mode = "groq_scientific_metadata_comparison"
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("120B scientific comparison failed")
        raise HTTPException(
            503,
            "The 120B deep-analysis model could not generate this scientific comparison. Check GROQ_API_KEY and GROQ_DEEP_ANALYSIS_MODEL, then retry. No raw metadata dump is being presented as an AI comparison."
        ) from exc
    comparison_mode = "groq_120b_scientific_comparison"
    return {"mode": comparison_mode, "items": found, "comparison_analysis": comparison_analysis}

@app.get("/api/analytics")
def analytics():
    try:
        items = list_catalogue(_inventory_lookup())
        scope = "SQLite-backed PSI catalogue"
    except Exception:
        items = INVESTIGATIONS
        scope = "team-supplied fallback inventory"
    asset_counts = Counter(asset for item in items for asset in (item.get("assets") or []))
    return {"total": len(items), "target_total": len(items), "asset_counts": dict(asset_counts), "metadata_only": sum(not (x.get("assets") or []) for x in items), "scope": scope}

@app.post("/api/upload")
async def upload(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    study_id: str = Form(...),
):
    """Extract a user-selected file and bind its evidence to one exact PSI session."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "The selected investigation session has expired. Reopen the same investigation and upload again.")
    if str(session.get("study_id", "")).casefold() != str(study_id).casefold():
        raise HTTPException(409, "Upload rejected: the selected study does not match this investigation session.")
    filename = os.path.basename(file.filename or "uploaded-research-file")
    suffix = os.path.splitext(filename)[1].lower()
    allowed = {".csv", ".tsv", ".json", ".txt", ".md", ".rtf", ".xml", ".html", ".log", ".dat", ".out", ".prn", ".pdf", ".xlsx", ".xlsm", ".xls", ".docx", ".pptx", ".gz"}
    if suffix not in allowed:
        raise HTTPException(415, "Supported files: CSV, TSV, JSON, TXT, MD, PDF, XLSX, XLS, DOCX, PPTX and supported text exports.")
    raw = await file.read()
    if len(raw) > 40 * 1024 * 1024:
        raise HTTPException(413, "Upload exceeds the 40 MB per-file limit.")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="firelytics_upload_", suffix=suffix, delete=False) as tmp:
            tmp.write(raw)
            temp_path = tmp.name
        extracted = _extract_file(__import__("pathlib").Path(temp_path))
        if extracted.get("status") == "extraction_failed":
            raise HTTPException(422, f"Could not extract {filename}: {extracted.get('error', 'unknown extraction error')}")
        return {
            "filename": filename,
            "study_id": session["study_id"],
            "session_id": session["session_id"],
            "format": extracted.get("format"),
            "status": extracted.get("status"),
            "extracted_text": extracted.get("content", ""),
            "columns": extracted.get("columns", []),
            "row_count": extracted.get("row_count_scanned"),
            "numeric_summary": extracted.get("numeric_summary", {}),
            "sheets": extracted.get("sheets", []),
            "pages": len(extracted.get("pages", [])),
            "preview_rows": extracted.get("sample_rows", []),
            "stored": False,
            "message": "Extracted for this request only; the uploaded file is not permanently stored.",
        }
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)

@app.post("/api/chat")
def chat(payload: ChatRequest):
    # Backward-compatible route. When a session ID is supplied, use the deep
    # file-grounded analysis pipeline; otherwise retain the catalogue assistant.
    session_id = getattr(payload, "session_id", None)
    if session_id:
        data = get_session(session_id)
        if not data:
            raise HTTPException(404, "Investigation session expired or not found")
        return answer_from_session(payload.message, data, payload.history)
    # Catalogue-level assistant: retrieve matching indexed records first, then
    # ask Groq to answer strictly from those records. File-level questions should
    # use a session_id and the evidence-grounded session pipeline above.
    try:
        retrieval = natural_language_search(payload.message, _inventory_lookup(), limit=8)
        hits = retrieval.get("results", [])
    except Exception:
        hits = []
        retrieval = {"mode": "keyword_fallback"}
    compact = [{k: item.get(k) for k in ("study_id", "title", "acronym", "summary", "objective", "approach", "hypothesis", "research_impacts", "research_area", "assets", "source_url", "matched_core_terms", "matched_related_terms") if item.get(k) is not None} for item in hits[:8]]
    if compact:
        try:
            client = _groq_client()
            if client:
                response = client.chat.completions.create(
                    model=__import__("os").getenv("GROQ_DEEP_ANALYSIS_MODEL", "openai/gpt-oss-120b"),
                    messages=[
                        {"role": "system", "content": "You are Firelytics AI using the 120B deep-analysis model. Answer the exact question in clear, natural language using only the retrieved PSI metadata. Synthesize rather than copying raw fields. Do not invent file contents, measurements, findings or citations. State specifically when the retrieved metadata is insufficient; for experimental findings, direct the user to open the exact investigation and upload its source file."},
                        {"role": "user", "content": json.dumps({"question": payload.message, "matching_investigations": compact, "previous_conversation": payload.history[-6:]}, ensure_ascii=False, default=str)},
                    ],
                    temperature=0.2, max_completion_tokens=1200,
                    reasoning_effort=__import__("os").getenv("GROQ_ANALYSIS_REASONING_EFFORT", "medium"),
                )
                return {"mode": "groq_catalogue_answer", "answer": response.choices[0].message.content or "The language model returned an empty answer.", "sources": [{"study_id": x["study_id"], "url": x.get("source_url")} for x in hits[:8]], "retrieval_mode": retrieval.get("mode")}
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("120B catalogue assistant answer failed")
            raise HTTPException(
                503,
                "The 120B deep-analysis model could not generate an answer. Check GROQ_API_KEY and GROQ_DEEP_ANALYSIS_MODEL, then retry. Search retrieval remains available independently."
            ) from exc
    answer = "No matching investigations were found in the local PSI catalogue. Try a different search query or open a specific investigation."
    return {"mode": "catalogue_no_match", "answer": answer, "sources": []}
