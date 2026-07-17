"""
Generation API: Generate QA test cases from selections using LLM.
Retrieval API: Fetch generated test cases with staleness detection.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DocumentNode, Selection, SelectionItem
from app.schemas import GenerateRequest, GenerationOut
from app.llm_service import generate_test_cases
from app.generation_store import get_generation_store

router = APIRouter(prefix="/api/generate", tags=["Generation & Retrieval"])


@router.post("/", response_model=GenerationOut)
def generate_from_selection(request: GenerateRequest, db: Session = Depends(get_db)):
    """
    Generate QA test cases from a selection.
    
    Policy on duplicate submissions:
    - If the same selection is submitted again AND its content hasn't changed,
      we return the existing generation (idempotent). This avoids unnecessary
      LLM calls and cost.
    - If the content HAS changed (staleness detected), a new generation is created
      to reflect the updated content.
    
    This policy was chosen because:
    1. Test cases should reflect the current document content
    2. Regenerating identical content is wasteful
    3. Users can still force regeneration by creating a new selection
    """
    # Validate selection exists
    selection = db.query(Selection).filter(Selection.id == request.selection_id).first()
    if not selection:
        raise HTTPException(status_code=404, detail=f"Selection not found: {request.selection_id}")

    if not selection.items:
        raise HTTPException(status_code=400, detail="Selection has no items")

    store = get_generation_store()

    # Check for existing generation with same content
    existing = store.get_generations_by_selection(request.selection_id)
    if existing:
        latest = existing[-1]
        # Check if content is still the same
        source_hashes = {sn["node_id"]: sn["content_hash"] for sn in latest.get("source_nodes", [])}
        all_same = True
        for item in selection.items:
            node = db.query(DocumentNode).filter(DocumentNode.id == item.node_id).first()
            if node and source_hashes.get(item.node_id) != node.content_hash:
                all_same = False
                break
        if all_same:
            # Return existing generation
            return _format_generation(latest, db)

    # Gather content from selection nodes
    content_parts = []
    source_nodes = []
    for item in selection.items:
        node = db.query(DocumentNode).filter(DocumentNode.id == item.node_id).first()
        if node:
            section_label = f"Section {node.section_number}" if node.section_number else node.heading
            content_parts.append(f"## {section_label}: {node.heading}\n\n{node.body_text}")
            source_nodes.append({
                "node_id": node.id,
                "heading": node.heading,
                "section_number": node.section_number,
                "version_id": node.version_id,
                "content_hash": node.content_hash,
            })

    if not content_parts:
        raise HTTPException(status_code=400, detail="No valid nodes found in selection")

    combined_content = "\n\n---\n\n".join(content_parts)

    # Call LLM
    result = generate_test_cases(combined_content)

    # Store generation
    generation = {
        "selection_id": request.selection_id,
        "source_nodes": source_nodes,
        "test_cases": result["test_cases"],
        "status": result["status"],
        "error_message": result.get("error_message"),
        "attempts": result.get("attempts", 0),
    }
    gen_id = store.save_generation(generation)
    generation["id"] = gen_id

    return _format_generation(generation, db)


@router.get("/by-selection/{selection_id}", response_model=list[GenerationOut])
def get_generations_by_selection(selection_id: str, db: Session = Depends(get_db)):
    """
    Retrieve all generated test cases for a selection.
    Includes staleness detection for each generation.
    """
    store = get_generation_store()
    generations = store.get_generations_by_selection(selection_id)
    return [_format_generation(g, db) for g in generations]


@router.get("/by-node/{node_id}", response_model=list[GenerationOut])
def get_generations_by_node(node_id: str, db: Session = Depends(get_db)):
    """
    Retrieve all generated test cases that reference a specific node.
    Includes staleness detection.
    """
    store = get_generation_store()
    generations = store.get_generations_by_node(node_id)
    return [_format_generation(g, db) for g in generations]


@router.get("/{generation_id}", response_model=GenerationOut)
def get_generation(generation_id: str, db: Session = Depends(get_db)):
    """
    Retrieve a specific generation by ID with staleness info.
    """
    store = get_generation_store()
    generation = store.get_generation(generation_id)
    if not generation:
        raise HTTPException(status_code=404, detail=f"Generation not found: {generation_id}")
    return _format_generation(generation, db)


@router.get("/", response_model=list[GenerationOut])
def list_generations(db: Session = Depends(get_db)):
    """List all generations."""
    store = get_generation_store()
    generations = store.list_all_generations()
    return [_format_generation(g, db) for g in generations]


def _format_generation(generation: dict, db: Session) -> GenerationOut:
    """
    Format a generation with staleness detection.
    
    Staleness check: Compare the content_hash stored at generation time
    with the current content_hash of each source node. If they differ,
    the test cases may no longer be accurate.
    
    Limitation: This is a binary stale/not-stale check. A one-word wording
    change triggers staleness the same as a changed pressure threshold.
    A more sophisticated approach would use semantic diff or change-impact
    scoring, but binary staleness is honest about what it can't distinguish.
    """
    staleness = {"is_stale": False, "stale_nodes": [], "total_nodes": 0}
    source_nodes = generation.get("source_nodes", [])
    staleness["total_nodes"] = len(source_nodes)

    for sn in source_nodes:
        node = db.query(DocumentNode).filter(DocumentNode.id == sn.get("node_id")).first()
        if node:
            if node.content_hash != sn.get("content_hash"):
                staleness["is_stale"] = True
                staleness["stale_nodes"].append({
                    "node_id": sn["node_id"],
                    "heading": sn.get("heading", ""),
                    "hash_at_generation": sn.get("content_hash"),
                    "current_hash": node.content_hash,
                })

    test_cases = []
    for tc in generation.get("test_cases", []):
        test_cases.append({
            "id": tc.get("id", ""),
            "title": tc.get("title", ""),
            "preconditions": tc.get("preconditions", ""),
            "steps": tc.get("steps", []),
            "expected_result": tc.get("expected_result", ""),
            "priority": tc.get("priority", "medium"),
            "section_reference": tc.get("section_reference", ""),
        })

    return GenerationOut(
        id=generation.get("id", ""),
        selection_id=generation.get("selection_id", ""),
        created_at=generation.get("created_at"),
        status=generation.get("status", "unknown"),
        error_message=generation.get("error_message"),
        test_cases=test_cases,
        source_nodes=source_nodes,
        staleness=staleness,
    )
