"""Browse API: Navigate the document tree, search, and compare versions."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, DocumentVersion, DocumentNode
from app.ingestion import compare_versions
from app.schemas import DocumentOut, NodeSummary, NodeDetail, NodeDiff, VersionSummary

router = APIRouter(prefix="/api/browse", tags=["Browse"])


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db)):
    """List all ingested documents with their versions."""
    docs = db.query(Document).all()
    results = []
    for doc in docs:
        versions = [
            VersionSummary(
                id=v.id,
                version_number=v.version_number,
                source_filename=v.source_filename,
                ingested_at=v.ingested_at,
            )
            for v in doc.versions
        ]
        results.append(DocumentOut(
            id=doc.id,
            name=doc.name,
            created_at=doc.created_at,
            versions=versions,
        ))
    return results


@router.get("/sections", response_model=list[NodeSummary])
def list_top_level_sections(
    document_id: str = Query(default="ct200_manual"),
    version: Optional[int] = Query(default=None, description="Version number (defaults to latest)"),
    db: Session = Depends(get_db),
):
    """
    List top-level sections of a document.
    Defaults to the latest version if no version parameter is provided.
    """
    version_id = _resolve_version(db, document_id, version)

    # Get root node(s) - level 0
    roots = (
        db.query(DocumentNode)
        .filter(DocumentNode.version_id == version_id, DocumentNode.level == 0)
        .order_by(DocumentNode.order_index)
        .all()
    )

    if not roots:
        return []

    # Get children of root (level 1 = top-level sections)
    root = roots[0]
    sections = (
        db.query(DocumentNode)
        .filter(DocumentNode.version_id == version_id, DocumentNode.parent_id == root.id)
        .order_by(DocumentNode.order_index)
        .all()
    )

    return [
        NodeSummary(
            id=s.id,
            heading=s.heading,
            level=s.level,
            section_number=s.section_number,
            content_hash=s.content_hash,
            has_children=bool(
                db.query(DocumentNode)
                .filter(DocumentNode.parent_id == s.id)
                .first()
            ),
        )
        for s in sections
    ]


@router.get("/nodes/{node_id}", response_model=NodeDetail)
def get_node(node_id: str, db: Session = Depends(get_db)):
    """Get a specific node by ID, including its children, full text, and content hash."""
    node = db.query(DocumentNode).filter(DocumentNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")

    children = (
        db.query(DocumentNode)
        .filter(DocumentNode.parent_id == node_id)
        .order_by(DocumentNode.order_index)
        .all()
    )

    return NodeDetail(
        id=node.id,
        heading=node.heading,
        level=node.level,
        section_number=node.section_number,
        body_text=node.body_text,
        content_hash=node.content_hash,
        structural_path=node.structural_path,
        parent_id=node.parent_id,
        children=[
            NodeSummary(
                id=c.id,
                heading=c.heading,
                level=c.level,
                section_number=c.section_number,
                content_hash=c.content_hash,
                has_children=bool(
                    db.query(DocumentNode).filter(DocumentNode.parent_id == c.id).first()
                ),
            )
            for c in children
        ],
    )


@router.get("/search", response_model=list[NodeSummary])
def search_nodes(
    q: str = Query(..., min_length=1, description="Search query"),
    document_id: str = Query(default="ct200_manual"),
    version: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Search/filter across node headings or body text."""
    version_id = _resolve_version(db, document_id, version)
    query_lower = f"%{q.lower()}%"

    nodes = (
        db.query(DocumentNode)
        .filter(
            DocumentNode.version_id == version_id,
            (DocumentNode.heading.ilike(query_lower) | DocumentNode.body_text.ilike(query_lower)),
        )
        .order_by(DocumentNode.order_index)
        .all()
    )

    return [
        NodeSummary(
            id=n.id,
            heading=n.heading,
            level=n.level,
            section_number=n.section_number,
            content_hash=n.content_hash,
            has_children=bool(
                db.query(DocumentNode).filter(DocumentNode.parent_id == n.id).first()
            ),
        )
        for n in nodes
    ]


@router.get("/diff", response_model=list[NodeDiff])
def get_version_diff(
    document_id: str = Query(default="ct200_manual"),
    version_a: int = Query(..., description="First version number"),
    version_b: int = Query(..., description="Second version number"),
    db: Session = Depends(get_db),
):
    """
    Compare two versions of a document.
    Returns a list of changes (added, removed, modified nodes).
    """
    changes = compare_versions(db, document_id, version_a, version_b)
    return [NodeDiff(**c) for c in changes]


@router.get("/nodes/{node_id}/changed", response_model=dict)
def check_node_changed(
    node_id: str,
    compare_version: Optional[int] = Query(default=None, description="Version to compare against"),
    db: Session = Depends(get_db),
):
    """
    Check if a specific node has changed across versions.
    Returns whether it changed and a lightweight diff summary if so.
    """
    node = db.query(DocumentNode).filter(DocumentNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")

    # Get the document version info
    version = db.query(DocumentVersion).filter(DocumentVersion.id == node.version_id).first()
    document_id = version.document_id

    # Find the comparison version
    if compare_version:
        compare_version_id = f"{document_id}_v{compare_version}"
    else:
        # Default to latest version
        latest = (
            db.query(DocumentVersion)
            .filter(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number.desc())
            .first()
        )
        if latest.id == node.version_id:
            return {"node_id": node_id, "changed": False, "message": "Node is from the latest version"}
        compare_version_id = latest.id

    # Find matching node in the other version by structural path
    matching = (
        db.query(DocumentNode)
        .filter(
            DocumentNode.version_id == compare_version_id,
            DocumentNode.structural_path == node.structural_path,
        )
        .first()
    )

    if not matching:
        return {
            "node_id": node_id,
            "changed": True,
            "change_type": "removed_in_other_version",
            "message": f"No matching node found in version {compare_version_id}",
        }

    if node.content_hash == matching.content_hash:
        return {
            "node_id": node_id,
            "changed": False,
            "matching_node_id": matching.id,
            "message": "Content is identical across versions",
        }

    return {
        "node_id": node_id,
        "changed": True,
        "change_type": "modified",
        "matching_node_id": matching.id,
        "diff_summary": _quick_diff(node, matching),
    }


def _quick_diff(node_a: DocumentNode, node_b: DocumentNode) -> dict:
    """Produce a lightweight diff between two nodes."""
    diff = {}
    if node_a.heading != node_b.heading:
        diff["heading_changed"] = {"from": node_a.heading, "to": node_b.heading}
    if node_a.body_text != node_b.body_text:
        lines_a = node_a.body_text.split("\n")
        lines_b = node_b.body_text.split("\n")
        diff["body_lines_before"] = len(lines_a)
        diff["body_lines_after"] = len(lines_b)
        # Show first difference
        for i, (la, lb) in enumerate(zip(lines_a, lines_b)):
            if la != lb:
                diff["first_difference_at_line"] = i + 1
                diff["before"] = la[:100]
                diff["after"] = lb[:100]
                break
    return diff


def _resolve_version(db: Session, document_id: str, version: Optional[int]) -> str:
    """Resolve version parameter to a version_id string."""
    if version:
        version_id = f"{document_id}_v{version}"
        exists = db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()
        if not exists:
            raise HTTPException(
                status_code=404,
                detail=f"Version {version} not found for document '{document_id}'",
            )
        return version_id
    else:
        latest = (
            db.query(DocumentVersion)
            .filter(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number.desc())
            .first()
        )
        if not latest:
            raise HTTPException(
                status_code=404,
                detail=f"No versions found for document '{document_id}'. Ingest a PDF first.",
            )
        return latest.id
