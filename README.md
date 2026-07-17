# CT-200 Document QA System

A backend API that parses the CardioTrack CT-200 blood pressure monitor technical manual (PDF) into a versioned hierarchical document tree, and generates QA test cases from selected sections using an LLM — with full traceability and staleness detection when the document is updated.

## Features

- **PDF Parsing** — Extracts document hierarchy (sections, subsections, tables, body text) preserving parent-child relationships
- **Document Versioning** — Ingest multiple versions of the same document without data loss
- **Browse & Search API** — Navigate the document tree, get node details, full-text search
- **Version Diff** — Compare any two versions and see what was added, removed, or modified
- **Selections** — Create named groups of nodes, pinned to specific versions and content hashes
- **LLM Test Case Generation** — Generate structured QA test cases from selected sections via Groq/Gemini/OpenRouter
- **Staleness Detection** — Automatically flags when generated test cases are based on outdated content

## Tech Stack

| Component | Technology |
|-----------|-----------|
| API Framework | FastAPI + Pydantic |
| Document Tree Storage | SQLAlchemy + SQLite |
| LLM Output Storage | MongoDB |
| PDF Parsing | PyMuPDF + pdfplumber |
| LLM Provider | Groq (Llama 3.1) |
| Deployment | Docker Compose |

## Quick Start

### Prerequisites

- Docker & Docker Compose installed
- A Groq API key (free at https://console.groq.com/keys)

### 1. Clone and configure

```bash
git clone <repo-url>
cd ct200-document-qa-system
cp .env.example .env
# Edit .env and add your Groq API key
```

### 2. Build and run

```bash
docker-compose build
docker-compose up -d
```

The API is now running at **http://localhost:8000**  
Interactive Swagger docs at **http://localhost:8000/docs**

### 3. Ingest the documents

```bash
# Ingest v1
curl -X POST http://localhost:8000/api/ingest/from-path \
  -d "pdf_path=/app/data/ct200_manual.pdf"

# Ingest v2
curl -X POST http://localhost:8000/api/ingest/from-path \
  -d "pdf_path=/app/data/ct200_manual_v2.pdf"
```

## V1 → V2 Re-Ingestion Flow (End-to-End Demo)

```bash
# Step 1: Ingest v1
curl -X POST http://localhost:8000/api/ingest/from-path \
  -d "pdf_path=/app/data/ct200_manual.pdf"

# Step 2: Browse sections
curl http://localhost:8000/api/browse/sections?version=1

# Step 3: Create a selection from safety sections (use real node IDs from step 2)
curl -X POST http://localhost:8000/api/selections/ \
  -H "Content-Type: application/json" \
  -d '{"name": "Safety Sections", "node_ids": ["<node_id_1>", "<node_id_2>"]}'

# Step 4: Generate test cases
curl -X POST http://localhost:8000/api/generate/ \
  -H "Content-Type: application/json" \
  -d '{"selection_id": "<selection_id>"}'

# Step 5: Ingest v2 (versioning — v1 preserved)
curl -X POST http://localhost:8000/api/ingest/from-path \
  -d "pdf_path=/app/data/ct200_manual_v2.pdf"

# Step 6: View diff between versions
curl "http://localhost:8000/api/browse/diff?version_a=1&version_b=2"

# Step 7: Check staleness of generated test cases
curl http://localhost:8000/api/generate/by-selection/<selection_id>
# → staleness field shows if test cases are outdated
```

Or run the automated demo script:

```bash
python demo_flow.py
```

## Running Tests

```bash
pip install pytest
cd ct200-document-qa-system
python -m pytest tests/ -v
```

22 tests covering:
- Out-of-order section numbering (3.4 before 3.3)
- Level jumps (2.1 → 2.1.1.1 with no intermediate levels)
- Duplicate headings producing distinct nodes with correct parents
- Version ingestion and comparison
- Content hash consistency and staleness detection

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/ingest/from-path` | Ingest a PDF from a file path |
| POST | `/api/ingest/` | Upload and ingest a PDF (multipart) |
| GET | `/api/browse/documents` | List all documents with versions |
| GET | `/api/browse/sections` | List top-level sections (version param) |
| GET | `/api/browse/nodes/{id}` | Get node detail with children and body text |
| GET | `/api/browse/search?q=...` | Full-text search across headings and body |
| GET | `/api/browse/diff?version_a=1&version_b=2` | Compare two versions |
| GET | `/api/browse/nodes/{id}/changed` | Check if a node changed across versions |
| POST | `/api/selections/` | Create a version-pinned selection |
| GET | `/api/selections/{id}` | Get selection with staleness per item |
| DELETE | `/api/selections/{id}` | Delete a selection |
| POST | `/api/generate/` | Generate test cases from a selection (LLM) |
| GET | `/api/generate/{id}` | Get a specific generation with staleness |
| GET | `/api/generate/by-selection/{id}` | Get all generations for a selection |
| GET | `/api/generate/by-node/{id}` | Get all generations referencing a node |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `groq` | LLM provider (`groq`, `gemini`, `openrouter`) |
| `LLM_API_KEY` | — | API key for the LLM provider |
| `LLM_MODEL` | `llama-3.1-8b-instant` | Model to use |
| `DATABASE_URL` | `sqlite:///./ct200.db` | SQLAlchemy database URL |
| `MONGODB_URI` | `mongodb://mongo:27017` | MongoDB connection string |
| `MONGODB_DB` | `ct200_qa` | MongoDB database name |

## Project Structure

```
ct200-document-qa-system/
├── app/
│   ├── main.py              # FastAPI application entry point
│   ├── config.py            # Environment configuration
│   ├── database.py          # SQLAlchemy setup
│   ├── models.py            # ORM models (Document, Version, Node, Selection)
│   ├── parser.py            # PDF → hierarchical tree parser
│   ├── ingestion.py         # Versioned document persistence + diff
│   ├── llm_service.py       # Multi-provider LLM with retry/validation
│   ├── generation_store.py  # MongoDB/JSON store for LLM outputs
│   ├── schemas.py           # Pydantic request/response schemas
│   └── routes/
│       ├── ingest.py        # Ingestion endpoints
│       ├── browse.py        # Browse, search, diff endpoints
│       ├── selections.py    # Selection CRUD endpoints
│       └── generate.py      # Generation + retrieval endpoints
├── tests/
│   ├── test_parser.py       # Parser edge case tests
│   └── test_versioning.py   # Versioning + staleness tests
├── data/
│   ├── ct200_manual.pdf     # Version 1 of the manual
│   └── ct200_manual_v2.pdf  # Version 2 of the manual
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── APPROACH.md              # Design decisions and decision log
├── demo_flow.py             # End-to-end demo script
└── visualize_tree.py        # Tree visualization utility
```

## Docker Commands

```bash
# Start
docker-compose up -d

# Stop
docker-compose down

# View logs
docker-compose logs -f api

# Rebuild after code changes
docker-compose build && docker-compose up -d
```
