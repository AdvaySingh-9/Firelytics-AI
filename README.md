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
