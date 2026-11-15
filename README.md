# Firelytics AI — React + FastAPI starter

Firelytics AI is a research-support interface for NASA's microgravity combustion research. This rebuild separates the React frontend from a FastAPI backend so the team can add database, NASA PSI ingestion, and AI/RAG services later without redesigning the UI.

## Current scope and data provenance

The React demo fallback catalogue contains **11 investigation IDs supplied by the project team**. The supplied SQLite database currently contains **26 investigations**, with report text indexed for 15. Neither source is a complete NASA PSI catalogue or a live mirror of NASA's repository.

| Study ID | Asset categories listed in supplied inventory |
|---|---|
| PSI-62 | Metadata only |
| PSI-60 | Metadata only |
| PSI-142 | Analyzed Data, Experimental Table |
| PSI-98 | Engineering Documents, Raw Data, Science Documents, Experimental Table |
| PSI-99 | Experimental Table, Raw Data, Science Documents |
| PSI-106 | Experimental Table, Raw Data |
| PSI-100 | Engineering Documents, Presentations, Raw Data, Science Documents, Experimental Table |
| PSI-21 | Experimental Table, Raw Data |
| PSI-68 | Experimental Table, Science Documents, Calibration, Engineering Documents, Raw Data |
| PSI-69 | Experimental Table, Engineering Documents, Presentations, Raw Data, Calibration, Science Documents |
| PSI-26 | Presentations, Science Documents, Engineering Documents, Raw Data, Experimental Table |

The asset list is based on the inventory provided by the team. The NASA PSI pages could not be parsed as readable text by the web retrieval layer during this build, so file-level contents have not been independently audited here. Open each official source link in the app before relying on it. The application deliberately distinguishes **not listed in the supplied inventory** from **confirmed absent in NASA PSI**.

## Project structure

```text
firelytics-ai/
├── frontend/                 # React + Vite user interface
│   ├── src/App.jsx            # Pages and interactions
│   ├── src/api.js             # FastAPI client + local fallback
│   ├── src/data.js            # Team-supplied starter inventory
│   ├── src/styles.css         # Responsive visual system
│   ├── .env.example
│   └── package.json
├── backend/                  # FastAPI service scaffold
│   ├── app/data.py            # In-memory starter inventory
│   ├── app/schemas.py         # Pydantic request models
│   ├── app/main.py            # API routes
│   ├── requirements.txt
│   └── run.py
└── README.md
```

## Run locally

### 1. Start FastAPI

```bash
cd backend
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

API docs: http://localhost:8000/docs
Health check: http://localhost:8000/api/health

### 2. Start React frontend

Open a second terminal:

```bash
cd frontend
npm install
copy .env.example .env
npm run dev
```

On macOS/Linux use `cp .env.example .env` instead of `copy`.

Frontend: http://localhost:5173

Set `VITE_API_BASE_URL=http://localhost:8000/api` in `frontend/.env` before starting Vite. The Settings & API page also allows applying a different API base URL for the current browser session and testing its health endpoint.

## Implemented frontend pages

- Overview dashboard with inventory metrics and asset coverage.
- AI Smart Search using Groq query understanding and SQLite FTS5/BM25 ranking over the supplied 26-record database (with a local fallback).
- Experiment Library with search, filters, sorting, details, and CSV export.
- Investigation details with NASA PSI links, asset availability, metadata export, and cautious demo explanation.
- Compare Studies for up to four records, including evidence-availability differences.
- Research Analytics calculated from the 11 supplied records.
- Safety Insights organized around prevention, detection, and suppression, with evidence-boundary notices.
- Data Explorer with local CSV/JSON parsing, preview, and JSON export.
- Research Assistant with a local-catalogue demo response.
- Settings & API with endpoint contract and backend health test.

## FastAPI endpoints

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/health` | Health check |
| GET | `/api/investigations` | List catalogue |
| GET | `/api/investigations/{study_id}` | Investigation detail |
| POST | `/api/search` | Groq query understanding + SQLite FTS5/BM25 ranked search |
| POST | `/api/explain` | Metadata-only explanation starter |
| POST | `/api/compare` | Compare catalogue records |
| GET | `/api/analytics` | Asset counts and coverage |
| GET | `/api/safety-insights` | Research themes, not safety recommendations |
| POST | `/api/upload` | Parse CSV/JSON in memory; does not persist |
| POST | `/api/chat` | Catalogue assistant starter; not an LLM |

## Backend integration plan

The investigation listing and search routes now read the supplied SQLite database through a search service. Several non-search demo routes still use the 11-record in-memory fallback catalogue; migrate those separately when you implement explanation and comparison.

Suggested future modules:

```text
backend/app/
├── routers/       # route modules by domain
├── services/      # search, ingestion, comparison, explanation
├── repositories/  # database access
├── models/        # SQLAlchemy models
├── schemas.py     # request/response contracts
└── main.py
```

Recommended future sequence:
1. Store PSI metadata and asset manifests in PostgreSQL.
2. Ingest and index the actual science/engineering documents and experimental tables.
3. Store raw files in object storage; avoid placing large binary files directly in relational rows.
4. Add a vector index and retrieval pipeline for document-grounded AI search.
5. Build explain/compare responses with citations to source files, table rows, or report pages.
6. Add authentication, upload limits, file validation, and production CORS configuration before public deployment.

## Scientific integrity rules

- A missing asset category in this team's list means **not listed**, not necessarily absent from NASA PSI.
- Metadata availability is not the same as having analyzed measurements.
- Never invent experimental values, findings, or citations.
- AI interpretations must be labelled separately from NASA-published findings.
- Every future safety insight should trace back to a source record, file, experimental condition, and observed result.
- Firelytics AI is a research-support tool, not an operational spacecraft fire-safety system.

## Notes

- Demo fallback is intentional: the UI remains usable if FastAPI is offline.
- The assistant and explain feature are catalogue-level demonstrations, not live LLM/RAG outputs.
- Uploaded files are parsed locally in the frontend preview. The FastAPI upload route is separately scaffolded for future integration and currently does not persist files.
- Before production deployment, restrict CORS to your deployed frontend origin and add authentication/rate limits as needed.


## AI-assisted PSI search (implemented)

The backend's `POST /api/search` now uses the existing 26-record SQLite database and its FTS5 index.

### Search flow

1. The frontend sends only the user's question to `POST /api/search`.
2. If `GROQ_API_KEY` is configured, Groq (`openai/gpt-oss-20b` by default) converts the question into a small, schema-validated JSON object containing core concepts, related terms, and scientific slots such as fuel and environment.
3. The backend searches the existing FTS5 index. It first looks for records containing all core concepts, then uses expanded concepts to find additional candidates.
4. The backend ranks candidates using weighted matches in title, keywords, objective, approach, hypothesis, impacts and report text, combined with SQLite BM25 relevance.
5. The API returns ranked investigation cards and the parsed query. It does not send the catalogue or report contents to Groq.

If Groq is unavailable or no key is configured, search remains usable through a lexical fallback. The response's `mode` indicates whether Groq or the fallback parsed the query.

### Configure Groq

```powershell
cd backend
copy .env.example .env
```

Add your key to `backend/.env`:

```env
GROQ_API_KEY=your_groq_api_key
GROQ_SEARCH_MODEL=openai/gpt-oss-20b
```

Install backend requirements and start FastAPI as described above. Search can be tested at `http://localhost:8000/docs` using `POST /api/search`:

```json
{
  "query": "How does heptane burn in microgravity?"
}
```

The response includes `parsed_query`, ranked `results`, each result's `score`, `match_type`, and matched terms. `all_core_concepts` means all extracted core terms matched in the indexed record; `expanded_concepts` means the result was retrieved through related terms.

### Ranking notes

- The LLM extracts concepts; it does not choose or rank investigations.
- SQLite FTS5/BM25 performs retrieval. A second deterministic scoring pass prioritizes core concept matches and gives more weight to titles, keywords and metadata than incidental mentions deep in report text.
- The database currently contains 26 investigations, with extracted report text indexed for 15. Results are limited by what has actually been ingested.
- File categories are displayed only when present in the supplied inventory. Missing inventory information is labelled unknown rather than treated as confirmed absence.
- The analysis LLM is a separate later integration. Search does not send entire papers or reports to the model.

## Temporary investigation sessions and deep file analysis

Opening an investigation now creates a **temporary evidence session**, but does not download the entire NASA file collection.

1. The backend loads local investigation metadata and any report text already indexed in the supplied SQLite database.
2. It calls the NASA PSI v2 file-manifest endpoint and recursively flattens the returned folder tree. The code does not assume fixed folder names, file names, file types, or file sizes.
3. It stores session-only equivalents of the asset inventory, capability matrix, dataset schemas, document chunks, investigation relationships and processing states under `backend/temporary/sessions/`. These are JSON/JSONL files with a session TTL; the SQLite database and its schema/data are not modified.
4. When the user asks a question, a fast local router identifies intent and evidence terms. The backend verifies those requirements against the temporary inventory and extracted evidence; routing never declares evidence available by itself.
5. Retrieval ranks the complete PSI manifest using filename, folder path, category, file type and size. Filename/folder matches outrank category-only matches. It fetches one bounded, question-ranked candidate batch when verified PSI evidence is weak. The manifest's `key` is retained as provenance but is not converted into a guessed public S3 URL. Files are downloaded only when PSI supplies a trusted direct URL or when `PSI_DOWNLOAD_URL_TEMPLATE` is configured with a download route verified from the official PSI browser network request. The public `nasa-psi` bucket does not expose the full `psi-data/PSI-xxx/` tree at its root, so guessing S3 URLs can produce systematic 404s.
6. Supported files are extracted into text or structured evidence. Successfully extracted original files are retained in the temporary workspace so users can download them; unsupported, empty or failed extractions are retained as well until session expiry/clear.
7. Evidence chunks and the manifest remain available for follow-up questions in the same session. The configured Groq analysis model (20B default) receives selected extracted evidence with source filenames and page/sheet/column provenance, not every file in the investigation.
8. Capability statuses distinguish `available`, `partial`, `unavailable` and `not_indexed`. In particular, a report being listed does not establish safety evidence: safety capability requires extracted content with substantive safety-related terms. Cross-investigation relationships remain `not_indexed` until separately verified.
9. The user can clear the active session; otherwise a TTL cleanup removes temporary workspace data. Session files can be rehydrated by another backend worker while the workspace remains available.

### Current extraction support and limits

- PDF: text extraction from up to 100 pages; scanned/image-only PDFs need OCR, which is not currently implemented.
- CSV/TSV: column names, up to 1,000,000 scanned rows, numeric summaries, and a sample of rows.
- XLS/XLSX/XLSM: sheet names, row/column counts, headers, observed column types, explicit units in headers, and sample rows.
- LOG and text-like DAT/OUT/PRN files: bounded text extraction when the content is recognizably textual; binary data files remain inventoried for a dedicated parser.
- TXT, Markdown, RTF, XML, HTML, JSON, DOCX, PPTX, ZIP/TAR archives, and standalone gzip-compressed files: best-effort text/structured extraction.
- Other binary/scientific formats are inventoried and retained temporarily, but require a format-specific parser before scientific analysis can use their contents.

The per-file, on-demand, session-budget, extracted-text, and 2-hour default TTL limits are configurable through `backend/.env`. `PSI_DOWNLOAD_URL_TEMPLATE` is optional and must be populated only after the exact official PSI download route and required parameters have been confirmed. A key-only manifest item without a verified download URL remains `no_download_url`; it is not sent to the analysis model as extracted evidence. The session manifest exposes download and extraction states so an unavailable file is not silently represented as analyzed evidence.

### Deep-analysis request flow

- `POST /api/sessions`: creates the temporary manifest session (no bulk file download).
- `POST /api/sessions/{session_id}/analyze`: classifies the question, verifies evidence availability, fetches relevant files if needed, ranks extracted evidence, and calls the analysis model.
- `POST /api/sessions/{session_id}/datasets`: selectively discovers and extracts experimental/modeling datasets and returns their temporary schemas.
- `GET /api/sessions/{session_id}`: returns the latest manifest, capability matrix and evidence inventory.
- `DELETE /api/sessions/{session_id}`: deletes the active temporary workspace.

If Groq is unavailable, the API returns an evidence preview and logs the provider's full diagnostic server-side. It does not present the preview as an AI-generated scientific conclusion.

### Offline deep-analysis checks

From the `backend/` directory, run:

```bash
python -m unittest discover -s tests -v
```

These tests cover question routing, evidence ranking, safety-capability verification, CSV column schema extraction, and temporary JSON/JSONL persistence. They do not make live NASA requests or call Groq.


## Temporary PSI investigation ingestion

When an investigation is opened, Firelytics creates a temporary session and discovers its PSI v2 manifest. Use **Download & process all files** in the investigation's NASA file inventory panel to process the complete accessible inventory in batches. The backend stores raw downloads under the session workspace, extracts supported formats, and deletes a raw file only after successful extraction. Extracted evidence and asset statuses remain in temporary JSON/JSONL session files until the session is cleared or expires. The permanent SQLite database is not modified.

The batch API is `POST /api/sessions/{session_id}/ingest` with `{"batch_size": 8}` (1–20). The default session download budget is 300 MB and the default per-file on-demand limit is 150 MB; configure `FIRELYTICS_MAX_SESSION_MB` and `FIRELYTICS_ON_DEMAND_MAX_FILE_MB` in `backend/.env` to change those limits. Restricted, oversized, unsupported, and failed assets are retained as explicit statuses rather than being counted as evidence.

For manifest entries without direct URLs, the downloader tries NASA's Geode study-download URL convention on the PSI host. NASA's public API documentation describes this URL shape for OSDR; the PSI-hosted route must still be verified with a small public file in PSI's browser Network panel. Configure `PSI_DOWNLOAD_URL_TEMPLATE` only if the captured PSI request differs. NASA's prepared-download workflow for requests above 1 GB is not automated by this application.

## PSI signed S3 download support (catalogue-wide)

The temporary ingestion service accepts official PSI repository object URLs from
`psi-repo-prod.s3.amazonaws.com` only when the decoded object path is under
`/psi-data/PSI-N/`. This covers short-lived AWS presigned links such as the
metadata ZIP links returned by the NASA PSI browser. The host is not accepted
for arbitrary bucket paths, and downloads are still subject to the configured
per-file/session limits and archive path-traversal protections.

The normal flow remains automatic: create a session for any `PSI-N` identifier,
let the v2 manifest populate the session inventory, then ask a question or use
**Download & process all files**. If the browser exposes a fresh signed URL that
is not present in the manifest, it can be added to the same temporary evidence
pipeline with:

```bash
curl -X POST http://localhost:8000/api/sessions/PSI-117_SESSION_ID/download-url \\
  -H "Content-Type: application/json" \\
  -d '{"url":"https://psi-repo-prod.s3.amazonaws.com/psi-data/PSI-117/metadata/fresh-file.zip?PRESIGNED_QUERY"}'
```

Replace the session ID and URL with current values. Presigned URLs expire; do
not reuse an expired link. The endpoint verifies that the object path belongs
to the active study, downloads into that session's temporary workspace, safely
extracts supported ZIP members, indexes extracted evidence, and makes it
available to the question router. The original archive is retained temporarily
for user download. Nothing is written into the permanent SQLite database.

The direct URL route is `POST /api/sessions/{session_id}/download-url` with
`{"url":"...","filename":"optional-name.zip"}`. It is useful for debugging
an official PSI browser download response; normal catalogue-wide operation
continues to use the live manifest for every study rather than a PSI-117-specific
URL.


## Model routing and deep scientific analysis

- Search remains on `openai/gpt-oss-20b` through `GROQ_SEARCH_MODEL`. The existing search service and FTS retrieval are unchanged.
- Investigation explanations, metadata-grounded chat, scientific comparisons, safety relevance and uploaded-file analysis use `openai/gpt-oss-120b` through `GROQ_DEEP_ANALYSIS_MODEL`.
- Question routing is deterministic and local; the selected scientific analysis task is then sent to the 120B model with the relevant investigation metadata and/or extracted user-uploaded evidence.
- If the 120B model is unavailable, the application reports that AI analysis was not generated instead of presenting raw metadata as an AI answer.
- Uploaded files are tagged with both the active investigation ID and session ID. The backend rejects mismatched upload sessions and never forwards one investigation's file evidence into another investigation's chat, safety analysis, dataset analysis, explanation or comparison.
- Opening an investigation does not download or extract PSI files automatically. Users open the official PSI page and upload the exact source they want analyzed.

Configure `backend/.env` with:

```env
GROQ_API_KEY=your_actual_groq_api_key
GROQ_SEARCH_MODEL=openai/gpt-oss-20b
GROQ_DEEP_ANALYSIS_MODEL=openai/gpt-oss-120b
GROQ_ANALYSIS_REASONING_EFFORT=medium
```

For a clean setup, copy `backend/.env.example` to `backend/.env`, add your own Groq API key, and install dependencies from the lockfiles. Do not commit `.env` files. See `MODEL_ROUTING_AND_FILE_ISOLATION.md` for details.


## Metadata-first analysis and user-provided evidence

Opening an investigation reads the complete structured PSI metadata from `database/data/psi.db` and does not fetch a live PSI file manifest or download repository files. The official PSI record link is provided so a user can open NASA's page and select a report or experiment dataset manually.

The investigation workspace accepts user-selected PDF, DOCX, PPTX, XLSX, XLS, CSV, TSV, JSON, TXT, Markdown and supported text exports. The backend extracts readable text/tables to a temporary file, sends extracted content with the user's question to the configured Groq analysis model, and deletes the temporary upload after extraction. Upload content is held in the active browser session only; it is not permanently stored. Unsupported or unextractable files are reported clearly.

For AI-generated explanations, chat answers and scientific comparisons, copy `backend/.env.example` to `backend/.env` and set a valid `GROQ_API_KEY`. The API health endpoint reports whether Groq analysis is configured. Without a key, exact metadata lookups and structured metadata comparison remain available, but the app labels AI interpretation as unavailable rather than pretending the LLM ran.
