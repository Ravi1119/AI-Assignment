# CT-200 Document QA API

A FastAPI backend that parses the CardioTrack CT-200 blood pressure monitor manual into a versioned, hierarchical document tree and generates QA test cases with traceability and staleness detection.

## Quick Start

### 1. Install Dependencies

```bash
cd project
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env to add your LLM API key (Groq free tier works well)
```

### 3. Run the Server

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://127.0.0.1:8000`. Interactive docs at `/docs`.

### 4. Ingest the Documents

```bash
# Ingest v1
curl -X POST "http://127.0.0.1:8000/api/ingest/from-path" \
  -d "pdf_path=../ct200_manual.pdf"

# Ingest v2 (creates version 2, preserves version 1)
curl -X POST "http://127.0.0.1:8000/api/ingest/from-path" \
  -d "pdf_path=../ct200_manual_v2.pdf"
```

### 5. Run the End-to-End Demo

```bash
python demo_flow.py
```

## Running Tests

```bash
pip install pytest
pytest tests/ -v
```

## V1 → V2 Re-Ingestion Flow

1. Ingest v1: `POST /api/ingest/from-path` with `ct200_manual.pdf`
2. Create a selection from v1 nodes: `POST /api/selections/`
3. Generate test cases: `POST /api/generate/`
4. Ingest v2: `POST /api/ingest/from-path` with `ct200_manual_v2.pdf`
5. Check diff: `GET /api/browse/diff?version_a=1&version_b=2`
6. Retrieve test cases: `GET /api/generate/by-selection/{id}` — staleness info included

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ingest/` | POST | Upload and ingest a PDF (multipart) |
| `/api/ingest/from-path` | POST | Ingest from local path |
| `/api/browse/documents` | GET | List all documents |
| `/api/browse/sections` | GET | Top-level sections (with version param) |
| `/api/browse/nodes/{id}` | GET | Node detail with children |
| `/api/browse/search?q=...` | GET | Search headings and text |
| `/api/browse/diff` | GET | Compare two versions |
| `/api/browse/nodes/{id}/changed` | GET | Check if node changed across versions |
| `/api/selections/` | GET/POST | List or create selections |
| `/api/selections/{id}` | GET/DELETE | Get or delete a selection |
| `/api/generate/` | POST | Generate test cases from selection |
| `/api/generate/{id}` | GET | Get a specific generation |
| `/api/generate/by-selection/{id}` | GET | Get generations for a selection |
| `/api/generate/by-node/{id}` | GET | Get generations referencing a node |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `groq` | LLM provider (groq, gemini, openrouter) |
| `LLM_API_KEY` | - | API key for the LLM provider |
| `LLM_MODEL` | `llama-3.1-8b-instant` | Model name |
| `DATABASE_URL` | `sqlite:///./ct200.db` | SQLAlchemy DB URL |
| `MONGODB_URI` | - | MongoDB connection (optional) |
| `JSON_STORE_PATH` | `./generated_outputs.json` | Fallback JSON store path |

## Architecture

- **Parser** (`app/parser.py`): PyMuPDF + pdfplumber for PDF text extraction and table handling
- **Models** (`app/models.py`): SQLAlchemy ORM for document tree, versions, selections
- **Generation Store** (`app/generation_store.py`): MongoDB or JSON file for LLM outputs
- **LLM Service** (`app/llm_service.py`): Multi-provider support with retry and validation
- **API Routes**: FastAPI routers for ingest, browse, selections, generation
