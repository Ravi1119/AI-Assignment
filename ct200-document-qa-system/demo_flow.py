"""
End-to-end demonstration script for the CT-200 Document QA API.

This script demonstrates the complete flow:
1. Ingest v1 of the manual
2. Browse sections and search
3. Create a selection
4. Generate test cases (requires LLM_API_KEY)
5. Ingest v2 of the manual
6. Detect changes between versions
7. Check staleness of previously generated test cases

Usage:
    1. Start the server: uvicorn app.main:app --reload
    2. Run this script: python demo_flow.py
"""

import httpx
import json
import time
import os

BASE_URL = "http://127.0.0.1:8000"

# Paths to PDFs (adjust if needed)
# Works both locally (PDFs in parent dir) and in Docker (PDFs in data/ dir)
PDF_V1_LOCAL = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ct200_manual.pdf"))
PDF_V1_DOCKER = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "ct200_manual.pdf"))
PDF_V1 = PDF_V1_DOCKER if os.path.exists(PDF_V1_DOCKER) else PDF_V1_LOCAL

PDF_V2_LOCAL = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ct200_manual_v2.pdf"))
PDF_V2_DOCKER = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "ct200_manual_v2.pdf"))
PDF_V2 = PDF_V2_DOCKER if os.path.exists(PDF_V2_DOCKER) else PDF_V2_LOCAL


def print_header(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def print_json(data):
    print(json.dumps(data, indent=2, default=str))


def main():
    client = httpx.Client(base_url=BASE_URL, timeout=30.0)

    # --- Step 1: Ingest v1 ---
    print_header("STEP 1: Ingest CT-200 Manual v1")
    resp = client.post(
        "/api/ingest/from-path",
        data={"pdf_path": PDF_V1, "document_id": "ct200_manual", "document_name": "CardioTrack CT-200 Manual"},
    )
    print(f"Status: {resp.status_code}")
    v1_data = resp.json()
    print_json(v1_data)

    # --- Step 2: Browse top-level sections ---
    print_header("STEP 2: Browse Top-Level Sections (v1)")
    resp = client.get("/api/browse/sections", params={"version": 1})
    sections = resp.json()
    print(f"Found {len(sections)} top-level sections:")
    for s in sections:
        print(f"  [{s['section_number']}] {s['heading']} (ID: {s['id']})")

    # --- Step 3: Get a specific node ---
    print_header("STEP 3: Get Node Detail (Section 4.2 - Error Codes)")
    # Find section 4.2
    target_id = None
    for s in sections:
        if s["section_number"] == "4":
            # Get children of section 4
            resp = client.get(f"/api/browse/nodes/{s['id']}")
            node_detail = resp.json()
            for child in node_detail.get("children", []):
                if child.get("section_number") == "4.2":
                    target_id = child["id"]
                    break
            break

    if target_id:
        resp = client.get(f"/api/browse/nodes/{target_id}")
        print_json(resp.json())
    else:
        print("Could not find section 4.2")

    # --- Step 4: Search ---
    print_header("STEP 4: Search for 'overpressure'")
    resp = client.get("/api/browse/search", params={"q": "overpressure"})
    results = resp.json()
    print(f"Found {len(results)} matching nodes:")
    for r in results:
        print(f"  [{r['section_number']}] {r['heading']}")

    # --- Step 5: Create a selection ---
    print_header("STEP 5: Create a Selection (Safety-critical sections)")
    # Collect node IDs for sections 4.1 and 4.2
    safety_node_ids = []
    for s in sections:
        if s["section_number"] == "4":
            resp = client.get(f"/api/browse/nodes/{s['id']}")
            node_detail = resp.json()
            for child in node_detail.get("children", []):
                if child.get("section_number") in ("4.1", "4.2", "4.3"):
                    safety_node_ids.append(child["id"])

    if safety_node_ids:
        resp = client.post(
            "/api/selections/",
            json={"name": "Safety Critical Sections", "node_ids": safety_node_ids},
        )
        selection = resp.json()
        print_json(selection)
        selection_id = selection["id"]
    else:
        print("Could not find safety section nodes")
        selection_id = None

    # --- Step 6: Generate test cases ---
    print_header("STEP 6: Generate QA Test Cases from Selection")
    if selection_id:
        resp = client.post("/api/generate/", json={"selection_id": selection_id})
        generation = resp.json()
        print(f"Status: {generation.get('status')}")
        if generation.get("test_cases"):
            for tc in generation["test_cases"]:
                print(f"\n  {tc['id']}: {tc['title']}")
                print(f"    Priority: {tc['priority']}")
                print(f"    Steps: {tc['steps']}")
                print(f"    Expected: {tc['expected_result']}")
        elif generation.get("error_message"):
            print(f"  Error: {generation['error_message']}")
            print("  (This is expected if LLM_API_KEY is not configured)")

    # --- Step 7: Ingest v2 ---
    print_header("STEP 7: Ingest CT-200 Manual v2")
    resp = client.post(
        "/api/ingest/from-path",
        data={"pdf_path": PDF_V2, "document_id": "ct200_manual", "document_name": "CardioTrack CT-200 Manual"},
    )
    v2_data = resp.json()
    print_json(v2_data)

    # --- Step 8: Compare versions ---
    print_header("STEP 8: Compare v1 vs v2 (Diff)")
    resp = client.get("/api/browse/diff", params={"version_a": 1, "version_b": 2})
    diff = resp.json()
    print(f"Found {len(diff)} changes:")
    for change in diff:
        print(f"  [{change['type'].upper()}] {change['path']} - {change['heading']}")
        if change.get("summary"):
            print(f"    Summary: {change['summary']}")

    # --- Step 9: Check staleness ---
    print_header("STEP 9: Check Staleness of Previous Generation")
    if selection_id:
        resp = client.get(f"/api/generate/by-selection/{selection_id}")
        generations = resp.json()
        if generations:
            gen = generations[-1]
            staleness = gen.get("staleness", {})
            print(f"  Is stale: {staleness.get('is_stale')}")
            if staleness.get("stale_nodes"):
                print(f"  Stale nodes ({len(staleness['stale_nodes'])}):")
                for sn in staleness["stale_nodes"]:
                    print(f"    - {sn['heading']}")
        else:
            print("  No generations found (LLM not configured)")

    # --- Step 10: Browse v2 sections ---
    print_header("STEP 10: Browse Sections (Latest = v2)")
    resp = client.get("/api/browse/sections")
    sections_v2 = resp.json()
    print(f"Found {len(sections_v2)} top-level sections in latest version:")
    for s in sections_v2:
        print(f"  [{s['section_number']}] {s['heading']}")

    print_header("DEMO COMPLETE")
    print("All flows demonstrated successfully.")
    print("Check /docs for the interactive Swagger UI.")


if __name__ == "__main__":
    main()
