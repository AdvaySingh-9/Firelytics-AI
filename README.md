# Firelytics AI
### NASA Space Apps Challenge 2026 | Challenge Theme: Flame in Freefall

<p align="center">
  **Making the science of fire in microgravity easier to discover, explore, and understand.**
</p>

---

## 1. Project Overview

Firelytics AI is an AI-powered research-support platform developed to help scientists, students, researchers, and space enthusiasts explore scientific investigations related to combustion and fire behaviour in space.

The project focuses on NASA's **Physical Sciences Informatics (PSI)** investigation catalogue, helping users search scientific investigations, explore research metadata, inspect available documents and datasets, ask questions about scientific evidence, and compare studies through an integrated interface.

Research about flame behaviour in microgravity is important for the future of human space exploration. Fire behaves differently in reduced-gravity environments, and understanding these differences is essential for improving knowledge of spacecraft fire hazards.

However, scientific information is often distributed across investigation records, technical reports, research papers, and experimental datasets. Finding relevant information and understanding it can be challenging, especially for students and researchers who are new to the subject.

**Firelytics AI addresses this challenge by bringing research discovery, AI-assisted exploration, document analysis, and investigation comparison into one platform.**

## 2. The Problem We Address

Understanding fire behaviour in microgravity is a significant scientific challenge.

On Earth, gravity-driven buoyancy influences the movement of hot gases and the shape of flames. In microgravity, buoyancy-driven convection is greatly reduced, which changes how flames behave and how combustion products move.

These differences make it important to investigate questions such as:

- How does flame behaviour change in microgravity?
- How do combustion conditions influence flame characteristics?
- What can space-based combustion experiments teach us?
- What research has already been conducted on fire behaviour in space?
- Where can students and scientists find relevant experimental observations and datasets?

A large amount of scientific knowledge is available through research investigations, but navigating multiple records and documents can require considerable time and technical familiarity.

### Our identified challenge

| Problem | Impact |
|---|---|
| Scientific information is distributed across multiple investigations and documents | Research discovery takes time |
| Technical reports can be lengthy and complex | Students may struggle to identify important information |
| Experimental datasets require careful inspection | Understanding available data can be difficult |
| Comparing multiple investigations manually is time-consuming | Identifying relevant research connections becomes harder |
| AI-generated information can lack clear evidence | Scientific reliability and verification become important |

## 3. Our Solution

Firelytics AI provides a unified AI-assisted research environment for exploring NASA PSI investigations.

Instead of manually navigating multiple investigation records and source files, users can search for relevant research, explore investigation details, inspect available research assets, and ask questions using natural language.

The platform combines:

- Investigation catalogue exploration.
- AI-assisted natural-language search.
- Research document and dataset inspection.
- Evidence-grounded question answering.
- Investigation comparison.
- Safety-related research relevance exploration.

Our objective is to make existing scientific knowledge more accessible without replacing original research papers, experimental evidence, or scientific judgement.

## 4. Key Features

### 4.1 Intelligent Research Search

Users can search scientific investigations using natural-language queries.

The platform uses AI-assisted query understanding together with SQLite full-text search and ranking to identify potentially relevant investigation records.

**Example research queries:**
- Flame behaviour in microgravity.
- Combustion experiments in space.
- Fire-related physical science investigations.
- Research involving flame characteristics and experimental conditions.

### 4.2 NASA PSI Investigation Explorer

Users can browse available Physical Sciences Informatics investigation records and explore their associated information.

The platform provides access to available investigation metadata and asset inventories, helping users understand what research material is associated with a particular investigation.

### 4.3 AI Research Assistant

The integrated research assistant allows users to ask questions about investigations and available scientific evidence.

Users can ask questions in natural language instead of manually searching through every available document.

Examples:
- Explain the objective of this investigation.
- What information is available in the research report?
- Summarize the extracted findings in this document.
- Which experimental variables are available in this dataset?

Responses depend on the metadata and successfully extracted evidence available to the application.

### 4.4 Scientific Document Analysis

Firelytics AI supports extraction of text from several common research document formats.

This helps users inspect research reports and ask questions about their contents.

Where available, source filenames and page-level context help users trace information back to the original material.

### 4.5 Experimental Dataset Inspection

Scientific datasets can contain important information about experimental conditions and observations.

The platform supports inspection of compatible tabular datasets, including information such as:

- Column names and headers.
- Worksheet names and dimensions.
- Observed data types.
- Sample rows.
- Numeric summaries.
- Units appearing in column headers.

This helps users understand the structure of available research datasets before exploring them further.

### 4.6 Investigation Comparison

Users can compare investigation records to explore similarities and differences in their available metadata.

This supports research discovery by helping users identify investigations that may be relevant to a shared topic.

### 4.7 Safety-Related Research Exploration

Fire safety is an important consideration for crewed space missions.

Firelytics AI can surface safety-related information when it is supported by relevant investigation metadata or extracted source content.

The platform does not assume that a document is safety-related merely because of its filename or asset category.

### 4.8 Temporary Research Workspaces

Users can create temporary investigation sessions to organize available research assets and extracted evidence.

These sessions support file ingestion, evidence inspection, and investigation-specific analysis without permanently modifying the local PSI catalogue database.

---

## 5. Relevance to Flame in Freefall

The NASA Space Apps Challenge theme *Flame in Freefall* highlights the importance of understanding combustion in microgravity.

Firelytics AI contributes to this research area by making existing scientific investigation information easier to discover and explore.

### How Firelytics AI supports this theme

| Research need | How our platform helps |
|---|---|
| Discover research on combustion in space | Search available NASA PSI investigation records |
| Understand scientific investigations | Explore objectives and investigation metadata |
| Explore research reports | Extract and analyze supported document content |
| Inspect available experimental data | Examine supported spreadsheet and tabular datasets |
| Ask research questions | Use AI-assisted, evidence-grounded analysis |
| Explore related investigations | Compare available investigation records |
| Investigate safety relevance | Surface information supported by available research evidence |

### Who can benefit?

**Students**

Students beginning research on *Flame in Freefall* can use Firelytics AI to discover relevant investigations, understand research objectives, and explore available scientific documents.

**Researchers and scientists**

Researchers can use the platform to navigate investigation records, inspect available research assets, and locate information relevant to their scientific questions.

**Space enthusiasts**

People interested in space science can use natural-language search and explanations to explore available research information.

---

## 6. How the Platform Works

Firelytics AI combines a web-based interface, backend research services, a local investigation database, and an AI integration.

### System Architecture

```text
                  USER
                    |
                    v
          REACT + VITE FRONTEND
                    |
                    v
              FASTAPI BACKEND
                    |
        +-----------+-----------+
        |           |           |
        v           v           v
   INVESTIGATION  SEARCH     RESEARCH
    SERVICES     SERVICES    SERVICES
        |           |           |
        v           v           v
     PSI DATA     SQLITE     FILE EXTRACTION
    DISCOVERY     FTS5       AND ANALYSIS
        |                       |
        |                       v
        |                  RESEARCH
        |                  EVIDENCE
        |                       |
        +-----------+-----------+
                    |
                    v
              GROQ AI API
                    |
                    v
          AI-ASSISTED ANALYSIS
                    |
                    v
          RESEARCH RESPONSE
```

### Technology Stack

| Technology | Purpose |
|---|---|
| React | Frontend user interface |
| Vite | Frontend development and build tooling |
| JavaScript | Frontend application logic |
| Python | Backend development |
| FastAPI | REST API and backend services |
| SQLite | Local PSI investigation catalogue |
| SQLite FTS5/BM25 | Full-text search and ranking |
| Groq API | AI-assisted query understanding and analysis |
| Pydantic | Request and response data validation |
| pypdf | PDF text extraction |
| openpyxl / xlrd | Spreadsheet extraction |
| python-docx | Word document extraction |
| python-pptx | PowerPoint text extraction |

## 7. Evidence-Based AI and Scientific Reliability

Scientific research requires accuracy, transparency, and traceability.

Firelytics AI is designed to distinguish between different types of available information.

| Evidence category | Description |
|---|---|
| Metadata-based information | Information obtained from investigation catalogue records |
| File-based evidence | Information extracted from available research documents or datasets |
| Unavailable evidence | Information that is not present in the available metadata or successfully extracted source content |

This distinction is important because investigation metadata should not be treated as experimental findings.

Similarly, the presence of a file in an investigation's asset inventory does not necessarily mean that the file has been downloaded or analyzed.

The platform is intended to identify evidence limitations rather than generate unsupported scientific conclusions.

**Scientific verification remains essential:** AI-generated interpretations should always be checked against the original research papers, reports, and datasets.

## 8. Supported File Formats

The current extraction pipeline supports several common research file formats.

| Format | Supported processing |
|---|---|
| PDF | Text extraction with page-level content |
| CSV / TSV | Tabular data and column inspection |
| XLS / XLSX / XLSM | Spreadsheet and worksheet inspection |
| TXT / LOG / Markdown | Text extraction |
| DOCX | Word document text extraction |
| PPTX | Presentation text extraction |
| JSON / XML / HTML / RTF | Best-effort text or structured extraction |
| ZIP / TAR / gzip | Best-effort archive and member extraction |

**Current limitations:**
- Scanned PDFs require OCR, which is not currently included.
- Image and video contents are not automatically interpreted by the text extraction workflow.
- Specialized binary scientific formats may require additional parsers.
- Large files are subject to configured processing and extraction limits.

## 9. Project Architecture

The repository is organized into frontend, backend, and database components.

```text
Firelytics-AI/
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── analysis_service.py
│   │   ├── search_service.py
│   │   ├── session_service.py
│   │   ├── psi_discovery.py
│   │   ├── schemas.py
│   │   └── data.py
│   │
│   ├── tests/
│   ├── .env.example
│   ├── requirements.txt
│   └── run.py
│
├── database/
│   ├── data/
│   │   └── psi.db
│   └── psi_db/
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── api.js
│   │   ├── data.js
│   │   └── styles.css
│   │
│   ├── .env.example
│   └── package.json
│
├── .gitignore
└── README.md
```

## 10. Installation and Setup

### Prerequisites

Before running Firelytics AI, install:

- Python 3.10 or newer.
- Node.js and npm.
- Git.
- A Groq API key for AI-powered functionality.

### Step 1: Clone the repository

```bash
git clone https://github.com/AdvaySingh-9/Firelytics-AI.git
cd Firelytics-AI
```

### Step 2: Configure the backend

Create and activate a Python virtual environment.

**Windows PowerShell**

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux**

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Create the environment configuration file:

```powershell
Copy-Item .env.example .env
```

For macOS/Linux:

```bash
cp .env.example .env
```

Add your Groq API key to `backend/.env`:

```env
GROQ_API_KEY=your_groq_api_key
```

Start the backend:

```bash
python run.py
```

The backend normally runs at:

```text
http://localhost:8000
```

API documentation:

```text
http://localhost:8000/docs
```

### Step 3: Configure the frontend

Open another terminal from the project root:

```bash
cd frontend
npm install
```

Create the frontend environment file:

```powershell
Copy-Item .env.example .env
```

For macOS/Linux:

```bash
cp .env.example .env
```

Configure:

```env
VITE_API_BASE_URL=http://localhost:8000/api
```

Start the frontend:

```bash
npm run dev
```

Open the local address displayed by Vite, normally:

```text
http://localhost:5173
```

### Step 4: Build for production

```bash
npm run build
```

The generated frontend build is stored in:

```text
frontend/dist/
```

---

## 11. API Overview

The FastAPI backend provides endpoints for investigation search, file processing, research analysis, and session management.

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | Backend health check |
| GET | `/api/investigations` | List investigations |
| GET | `/api/investigations/{study_id}` | Investigation details |
| POST | `/api/search` | Search investigations |
| POST | `/api/sessions` | Create research session |
| GET | `/api/sessions/{session_id}` | Retrieve session details |
| POST | `/api/sessions/{session_id}/ingest` | Ingest research files |
| POST | `/api/sessions/{session_id}/download-url` | Resolve supported file download URL |
| GET | `/api/sessions/{session_id}/files/{asset_id}` | Retrieve session file |
| POST | `/api/sessions/{session_id}/analyze` | Analyze session evidence |
| POST | `/api/sessions/{session_id}/datasets` | Inspect datasets |
| DELETE | `/api/sessions/{session_id}` | Delete temporary session |
| POST | `/api/explain` | Explain investigation |
| POST | `/api/compare` | Compare investigations |
| GET | `/api/analytics` | Catalogue analytics |
| POST | `/api/upload` | Upload and parse files |
| POST | `/api/chat` | Research assistant |

For exact request and response formats, refer to the interactive FastAPI documentation at `/docs`.

## 12. Data Handling and Privacy Considerations

Firelytics AI uses temporary investigation sessions to manage uploaded and retrieved research evidence.

- Temporary sessions are separate from the local SQLite investigation catalogue.
- The default session lifetime is two hours.
- Session lifetime and file-size limits can be configured through environment variables.
- Temporary session data can include extracted text, structured evidence, processing information, and retained source files.
- Users should only upload materials they are authorized to share with the configured deployment and AI provider.

Do not commit API keys or environment files to the repository.

## 13. Testing

Backend tests can be executed from the `backend/` directory:

```bash
python -m unittest discover -s tests -v
```

To build the frontend:

```bash
cd frontend
npm run build
```

These checks do not independently verify live NASA PSI downloads, Groq API availability, model quotas, or complete end-to-end deployment behaviour.

## 14. Future Scope

The following are potential improvements for future development:

- **OCR integration:** Extract text from scanned research papers and image-based PDFs.
- **Advanced scientific visualization:** Provide richer ways to explore experimental datasets.
- **Visual research analysis:** Support interpretation of relevant scientific images and videos.
- **Expanded scientific formats:** Add parsers for specialized experimental and simulation formats.
- **Improved evidence navigation:** Make it easier to move from an AI-generated statement to its exact source passage.
- **Research knowledge discovery:** Explore ways to connect related investigations and scientific topics.
- **Evaluation and validation:** Develop systematic tests for retrieval relevance and scientific answer faithfulness.

## 15. Impact and Importance

Firelytics AI aims to reduce the effort involved in discovering and understanding research about combustion and fire behaviour in microgravity.

Its value lies in making existing scientific information easier to explore and helping users identify which sources may be relevant to their research questions.

For students, it provides a starting point for exploring the science of *Flame in Freefall*.

For scientists, it offers a unified way to search investigation records and inspect available research evidence.

For the broader space-science community, it supports greater accessibility to existing research knowledge.

**Our vision is to make scientific discovery more accessible, transparent, and evidence-aware—supporting the research needed to better understand fire in space.**

## 16. Contributing

Contributions and suggestions are welcome.

1. Fork the repository.
2. Create a feature branch.
3. Make your changes.
4. Add or update tests where appropriate.
5. Run the backend tests and frontend build.
6. Submit a Pull Request describing your changes.

Please do not commit API keys, `.env` files, virtual environments, or temporary application data.

## 17. License

See the [`LICENSE`](LICENSE) file in this repository for licensing information.

---

<p align="center">

### Firelytics AI

**Explore the science. Understand the evidence. Make space research more accessible.**

*Built for NASA Space Apps Challenge 2026 — Flame in Freefall.*

</p>