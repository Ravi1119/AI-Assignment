"""
CardioTrack CT-200 Document Management & QA Test Case Generation API

A FastAPI backend that:
1. Parses the CT-200 PDF manual into a hierarchical tree
2. Supports document versioning (v1 -> v2)
3. Provides Browse, Selection, and Generation APIs
4. Detects content staleness for generated test cases
"""

from fastapi import FastAPI
from app.database import init_db
from app.routes import ingest, browse, selections, generate

app = FastAPI(
    title="CT-200 Document QA API",
    description=(
        "Backend API for parsing the CardioTrack CT-200 manual into a versioned, "
        "hierarchical tree and generating QA test cases with traceability and staleness detection."
    ),
    version="1.0.0",
)

# Initialize database on startup
@app.on_event("startup")
def startup():
    init_db()

# Register routers
app.include_router(ingest.router)
app.include_router(browse.router)
app.include_router(selections.router)
app.include_router(generate.router)


@app.get("/", tags=["Health"])
def root():
    return {
        "service": "CT-200 Document QA API",
        "version": "1.0.0",
        "endpoints": {
            "ingest": "/api/ingest/",
            "browse_sections": "/api/browse/sections",
            "browse_node": "/api/browse/nodes/{node_id}",
            "search": "/api/browse/search?q=...",
            "diff": "/api/browse/diff?version_a=1&version_b=2",
            "selections": "/api/selections/",
            "generate": "/api/generate/",
            "docs": "/docs",
        },
    }
