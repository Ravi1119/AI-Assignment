"""Pydantic schemas for request/response validation."""

from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime


# --- Document & Version Schemas ---

class DocumentOut(BaseModel):
    id: str
    name: str
    created_at: Optional[datetime] = None
    versions: list["VersionSummary"] = []

    class Config:
        from_attributes = True


class VersionSummary(BaseModel):
    id: str
    version_number: int
    source_filename: str
    ingested_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# --- Node Schemas ---

class NodeSummary(BaseModel):
    id: str
    heading: str
    level: int
    section_number: Optional[str] = None
    content_hash: str
    has_children: bool = False

    class Config:
        from_attributes = True


class NodeDetail(BaseModel):
    id: str
    heading: str
    level: int
    section_number: Optional[str] = None
    body_text: str
    content_hash: str
    structural_path: str
    parent_id: Optional[str] = None
    children: list[NodeSummary] = []

    class Config:
        from_attributes = True


class NodeDiff(BaseModel):
    type: str  # "modified", "added", "removed"
    path: str
    heading: str
    node_id_v1: Optional[str] = None
    node_id_v2: Optional[str] = None
    summary: Optional[str] = None


# --- Selection Schemas ---

class SelectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    node_ids: list[str] = Field(..., min_length=1)


class SelectionOut(BaseModel):
    id: str
    name: str
    created_at: Optional[datetime] = None
    items: list["SelectionItemOut"] = []

    class Config:
        from_attributes = True


class SelectionItemOut(BaseModel):
    node_id: str
    version_id: str
    content_hash_at_selection: str
    heading: Optional[str] = None
    is_stale: bool = False

    class Config:
        from_attributes = True


# --- Generation Schemas ---

class GenerateRequest(BaseModel):
    selection_id: str


class TestCaseOut(BaseModel):
    id: str
    title: str
    preconditions: str = ""
    steps: list[str] = []
    expected_result: str = ""
    priority: str = "medium"
    section_reference: str = ""


class GenerationOut(BaseModel):
    id: str
    selection_id: str
    created_at: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    test_cases: list[TestCaseOut] = []
    source_nodes: list[dict] = []
    staleness: Optional[dict] = None


# --- Ingestion Schemas ---

class IngestRequest(BaseModel):
    document_id: str = "ct200_manual"
    document_name: str = "CardioTrack CT-200 Manual"
    source_filename: str


class IngestResponse(BaseModel):
    version_id: str
    version_number: int
    document_id: str
    node_count: int
    message: str
