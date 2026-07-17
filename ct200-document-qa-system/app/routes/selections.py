"""Selection API: Create and manage named selections of document nodes."""

import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DocumentNode, Selection, SelectionItem
from app.schemas import SelectionCreate, SelectionOut, SelectionItemOut

router = APIRouter(prefix="/api/selections", tags=["Selections"])


@router.post("/", response_model=SelectionOut)
def create_selection(request: SelectionCreate, db: Session = Depends(get_db)):
    """
    Create a named selection of node IDs.
    
    Selections are version-pinned: they capture the exact version and content hash
    of each node at creation time, so they remain resolvable even after re-ingestion.
    """
    # Validate all node IDs exist
    nodes = []
    for node_id in request.node_ids:
        node = db.query(DocumentNode).filter(DocumentNode.id == node_id).first()
        if not node:
            raise HTTPException(
                status_code=404,
                detail=f"Node not found: {node_id}. Ensure you're using valid node IDs from the browse API.",
            )
        nodes.append(node)

    # Create selection
    selection_id = str(uuid.uuid4())[:8]
    selection = Selection(id=selection_id, name=request.name)
    db.add(selection)
    db.flush()

    # Create selection items (version-pinned)
    for node in nodes:
        item = SelectionItem(
            selection_id=selection_id,
            node_id=node.id,
            version_id=node.version_id,
            content_hash_at_selection=node.content_hash,
        )
        db.add(item)

    db.commit()
    db.refresh(selection)

    return _format_selection(selection, db)


@router.get("/", response_model=list[SelectionOut])
def list_selections(db: Session = Depends(get_db)):
    """List all selections."""
    selections = db.query(Selection).order_by(Selection.created_at.desc()).all()
    return [_format_selection(s, db) for s in selections]


@router.get("/{selection_id}", response_model=SelectionOut)
def get_selection(selection_id: str, db: Session = Depends(get_db)):
    """
    Get a selection by ID, including staleness status for each item.
    
    An item is stale if the node's current content_hash differs from the
    content_hash_at_selection — meaning the document was re-ingested and
    that section's content changed.
    """
    selection = db.query(Selection).filter(Selection.id == selection_id).first()
    if not selection:
        raise HTTPException(status_code=404, detail=f"Selection not found: {selection_id}")
    return _format_selection(selection, db)


@router.delete("/{selection_id}")
def delete_selection(selection_id: str, db: Session = Depends(get_db)):
    """Delete a selection."""
    selection = db.query(Selection).filter(Selection.id == selection_id).first()
    if not selection:
        raise HTTPException(status_code=404, detail=f"Selection not found: {selection_id}")
    db.delete(selection)
    db.commit()
    return {"message": f"Selection '{selection_id}' deleted"}


def _format_selection(selection: Selection, db: Session) -> SelectionOut:
    """Format a selection with staleness info."""
    items = []
    for item in selection.items:
        node = db.query(DocumentNode).filter(DocumentNode.id == item.node_id).first()
        is_stale = False
        heading = None
        if node:
            heading = node.heading
            is_stale = node.content_hash != item.content_hash_at_selection
        items.append(SelectionItemOut(
            node_id=item.node_id,
            version_id=item.version_id,
            content_hash_at_selection=item.content_hash_at_selection,
            heading=heading,
            is_stale=is_stale,
        ))

    return SelectionOut(
        id=selection.id,
        name=selection.name,
        created_at=selection.created_at,
        items=items,
    )
