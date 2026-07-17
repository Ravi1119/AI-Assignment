"""Ingestion API: Upload and parse PDF documents."""

import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DocumentVersion, DocumentNode
from app.ingestion import ingest_document
from app.schemas import IngestResponse

router = APIRouter(prefix="/api/ingest", tags=["Ingestion"])

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")


@router.post("/", response_model=IngestResponse)
def ingest_pdf(
    document_id: str = Form(default="ct200_manual"),
    document_name: str = Form(default="CardioTrack CT-200 Manual"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Ingest a PDF document as a new version.
    
    If the document already exists, creates a new version.
    Previous versions are preserved.
    """
    # Save uploaded file to data directory
    os.makedirs(DATA_DIR, exist_ok=True)
    file_path = os.path.join(DATA_DIR, file.filename)
    with open(file_path, "wb") as f:
        content = file.file.read()
        f.write(content)

    try:
        version = ingest_document(
            db=db,
            pdf_path=file_path,
            document_id=document_id,
            document_name=document_name,
            source_filename=file.filename,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")

    node_count = db.query(DocumentNode).filter(
        DocumentNode.version_id == version.id
    ).count()

    return IngestResponse(
        version_id=version.id,
        version_number=version.version_number,
        document_id=document_id,
        node_count=node_count,
        message=f"Successfully ingested '{file.filename}' as version {version.version_number}",
    )


@router.post("/from-path", response_model=IngestResponse)
def ingest_from_path(
    pdf_path: str = Form(...),
    document_id: str = Form(default="ct200_manual"),
    document_name: str = Form(default="CardioTrack CT-200 Manual"),
    db: Session = Depends(get_db),
):
    """
    Ingest a PDF from a local file path (convenience endpoint for testing).
    """
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail=f"File not found: {pdf_path}")

    source_filename = os.path.basename(pdf_path)

    try:
        version = ingest_document(
            db=db,
            pdf_path=pdf_path,
            document_id=document_id,
            document_name=document_name,
            source_filename=source_filename,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")

    node_count = db.query(DocumentNode).filter(
        DocumentNode.version_id == version.id
    ).count()

    return IngestResponse(
        version_id=version.id,
        version_number=version.version_number,
        document_id=document_id,
        node_count=node_count,
        message=f"Successfully ingested '{source_filename}' as version {version.version_number}",
    )
