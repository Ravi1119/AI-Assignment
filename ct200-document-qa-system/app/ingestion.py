"""
Document ingestion service: parses PDF and persists the tree to the database.
Handles versioning and cross-version node matching.
"""

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Document, DocumentVersion, DocumentNode
from app.parser import parse_pdf, ParsedNode, generate_node_id


def ingest_document(
    db: Session,
    pdf_path: str,
    document_id: str,
    document_name: str,
    source_filename: str,
) -> DocumentVersion:
    """
    Ingest a PDF as a new version of a document.
    
    If the document doesn't exist, creates it.
    If it exists, creates a new version without destroying previous ones.
    
    Returns the created DocumentVersion.
    """
    # Get or create document
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        doc = Document(id=document_id, name=document_name)
        db.add(doc)
        db.flush()

    # Determine next version number
    existing_versions = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number.desc())
        .all()
    )
    next_version = (existing_versions[0].version_number + 1) if existing_versions else 1

    # Create version record
    version_id = f"{document_id}_v{next_version}"
    version = DocumentVersion(
        id=version_id,
        document_id=document_id,
        version_number=next_version,
        source_filename=source_filename,
    )
    db.add(version)
    db.flush()

    # Parse PDF
    tree_roots = parse_pdf(pdf_path)

    # Persist tree nodes recursively
    _persist_tree(db, version_id, tree_roots, parent_id=None)

    db.commit()
    return version


def _persist_tree(
    db: Session,
    version_id: str,
    nodes: list[ParsedNode],
    parent_id: Optional[str],
):
    """Recursively persist parsed nodes to the database."""
    for node in nodes:
        node_id = generate_node_id(
            version_id, node.section_number, node.heading, node.order_index
        )
        content_hash = node.content_hash
        structural_path = node.structural_path

        db_node = DocumentNode(
            id=node_id,
            version_id=version_id,
            heading=node.heading,
            level=node.level,
            section_number=node.section_number,
            body_text=node.body_text,
            content_hash=content_hash,
            parent_id=parent_id,
            order_index=node.order_index,
            structural_path=structural_path,
        )
        db.add(db_node)
        db.flush()

        # Recurse into children
        if node.children:
            _persist_tree(db, version_id, node.children, parent_id=node_id)


def compare_versions(db: Session, document_id: str, version_a: int, version_b: int) -> list[dict]:
    """
    Compare two versions of a document and return a list of changes.
    
    Matching strategy: path-based matching using structural_path.
    - Nodes with the same structural_path across versions are considered the same logical node.
    - If content_hash differs, the node has changed.
    - Nodes present in only one version are additions or removals.
    
    Known limitation: If a section is renumbered (e.g., "3.2" becomes "3.3"),
    path-based matching will see it as a removal + addition rather than a move.
    This is acceptable for the CT-200 manual where renumbering doesn't happen
    between v1 and v2.
    """
    va_id = f"{document_id}_v{version_a}"
    vb_id = f"{document_id}_v{version_b}"

    nodes_a = db.query(DocumentNode).filter(DocumentNode.version_id == va_id).all()
    nodes_b = db.query(DocumentNode).filter(DocumentNode.version_id == vb_id).all()

    map_a = {n.structural_path: n for n in nodes_a}
    map_b = {n.structural_path: n for n in nodes_b}

    changes = []

    all_paths = set(map_a.keys()) | set(map_b.keys())
    for path in sorted(all_paths):
        node_a = map_a.get(path)
        node_b = map_b.get(path)

        if node_a and node_b:
            if node_a.content_hash != node_b.content_hash:
                changes.append({
                    "type": "modified",
                    "path": path,
                    "heading": node_b.heading,
                    "node_id_v1": node_a.id,
                    "node_id_v2": node_b.id,
                    "summary": _diff_summary(node_a, node_b),
                })
        elif node_a and not node_b:
            changes.append({
                "type": "removed",
                "path": path,
                "heading": node_a.heading,
                "node_id_v1": node_a.id,
            })
        else:
            changes.append({
                "type": "added",
                "path": path,
                "heading": node_b.heading,
                "node_id_v2": node_b.id,
            })

    return changes


def _diff_summary(node_a: DocumentNode, node_b: DocumentNode) -> str:
    """Generate a lightweight diff summary between two node versions."""
    parts = []
    if node_a.heading != node_b.heading:
        parts.append(f"Heading changed: '{node_a.heading}' -> '{node_b.heading}'")

    if node_a.body_text != node_b.body_text:
        # Find specific differences
        lines_a = set(node_a.body_text.split("\n"))
        lines_b = set(node_b.body_text.split("\n"))
        added = lines_b - lines_a
        removed = lines_a - lines_b

        if removed:
            parts.append(f"Removed {len(removed)} line(s)")
        if added:
            parts.append(f"Added {len(added)} line(s)")

    return "; ".join(parts) if parts else "Content hash changed"
