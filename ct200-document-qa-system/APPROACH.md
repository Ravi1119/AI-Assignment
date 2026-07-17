# Approach Document

## OCR/Document Parsing Approach

**Selected approach**: PyMuPDF (`fitz`) for text extraction + `pdfplumber` for table extraction.

**Why**: The CT-200 PDF is a text-based PDF (not scanned images), so full OCR (Tesseract, etc.) is unnecessary overhead. PyMuPDF provides fast, accurate text extraction with positional information. pdfplumber adds robust table detection that PyMuPDF's text mode tends to flatten into unstructured lines.

**Why not full OCR**: OCR introduces error where none needs to exist. The PDF has embedded text — running OCR on it would add noise and processing time with no accuracy benefit.

## Hierarchy Reconstruction Strategy

The parser uses a **stack-based parent assignment** algorithm:

1. Lines matching the regex `^(\d+(?:\.\d+)*)\s+(.+)$` are identified as headings.
2. The heading level is determined by counting the dot-separated parts (e.g., "2.1.1.1" → level 4).
3. A stack tracks the current ancestry chain. When a new heading arrives:
   - Pop the stack until we find a node with a strictly lower level.
   - That node becomes the parent.
4. Body text accumulates until the next heading, then is flushed to the current node.

This approach correctly handles:
- **Out-of-order numbering**: 3.4 before 3.3 works because parent assignment uses level comparison, not number ordering.
- **Level jumps**: 2.1 → 2.1.1.1 works because the stack pops to 2.1 (level 2), which is < 4.
- **Duplicate headings**: Section numbers make them unique ("4.2" vs "7.1"), and IDs incorporate the section number.

## Structural Inconsistencies Discovered

1. **Section 3.4 appears before 3.3** — The PDF has "Auto Shutoff" (3.4) before "Result Display and Classification" (3.3). This is intentional in the test document to verify parsers handle non-sequential numbering.

2. **Level jump from 2.1 to 2.1.1.1** — There's no 2.1.1 section. "Battery Life Under Typical Use" jumps directly to level 4. This tests that the parser doesn't require intermediate heading levels to exist.

3. **Duplicate heading "Error Codes"** — Appears as both section 4.2 (the definitive error code table) and section 7.1 (troubleshooting reference). Tests that duplicate text produces distinct nodes with correct parents.

4. **Tables embedded as line sequences** — The specifications table (section 2.1) and error codes table (4.2) appear as alternating key-value lines in raw text extraction.

5. **Cross-references in body text** — Section 3.3 references "(see 2.1, 4.3 for related specifications and alarm thresholds)" which adds parsing noise.

## What My Initial Implementation Failed To Handle

1. **Table detection in body text**: First pass treated table rows as regular body text, making section 2.1 and 4.2 bodies a mess of alternating words. Fixed by using pdfplumber's table extraction and formatting them as structured text.

2. **Title extraction**: Initially the document title (spanning multiple lines before section 1) was lost. Fixed by collecting all text before the first numbered heading as the root node.

3. **Body text bleeding across pages**: Lines at page boundaries could split mid-sentence. Fixed by treating all pages as a continuous text stream rather than parsing page-by-page.

## How I Identified These Failures

- **Manual inspection**: Printed the full parsed tree and visually verified against the PDF.
- **Unit tests**: Wrote specific tests for each known irregularity before fixing them (test-first).
- **Hash comparison**: Compared content hashes between v1 and v2 for sections known to be unchanged (e.g., 1.1 Intended Use) — hash mismatch revealed body text inconsistencies.

## Version Matching Strategy

**Strategy**: Path-based matching using `structural_path`.

Each node gets a path like `CardioTrack.../1/1.1` constructed from its ancestry. Nodes with the same structural_path across versions are considered the same logical node.

**Why path-based over fuzzy matching**: 
- Deterministic — same input always produces same match
- Handles duplicate headings naturally (different paths)
- Simple to reason about and debug

**Known failure modes**:
- If a section is renumbered between versions (e.g., "3.2" becomes "3.3"), path matching treats it as a deletion + addition. This doesn't happen in the CT-200 v1→v2 transition, but would be a problem for documents with major restructuring.
- If the document title changes, all paths shift. Mitigated by using section numbers as the primary path component rather than heading text.

## LLM Prompt Design & Structured Output Strategy

**Prompt design**: System prompt defines the exact JSON schema. User prompt provides the document sections with section numbers for reference. Temperature set to 0.3 for consistent outputs.

**Structured output validation**:
1. Try `json.loads()` on raw response
2. Try extracting from markdown fences (common LLM artifact)
3. Try finding JSON object anywhere in response
4. Validate required fields exist in each test case
5. Fill defaults for missing optional fields

**Retry strategy**: Up to 2 retries on validation failure. HTTP errors (auth, rate limit) are not retried. Timeout errors are retried.

**Duplicate submission policy**: If a selection is submitted again with unchanged content, return the existing generation (idempotent). If content changed (staleness), generate fresh.

## Staleness Detection Design

A generation stores the `content_hash` of each source node at generation time. At retrieval, current hashes are compared against stored hashes. Any mismatch marks the generation as stale.

**Limitation**: This is binary stale/not-stale. A one-word wording fix triggers staleness identically to a changed pressure threshold (300→250 cycles). A more sophisticated system would use semantic similarity scoring or change-impact analysis, but that introduces false confidence. Binary staleness is honest: "something changed, verify manually."

**What I'd do with more time**: Add a "change severity" score based on the proportion of body text that changed (Levenshtein ratio), and let users set a threshold for what constitutes meaningful staleness.

---

## Decision Log

### 1. What's the one part most likely to silently give wrong results?

**The parser's heading detection regex.** If a numbered list in body text (like the blood pressure classification "1. Normal: systolic < 120...") matches the heading pattern, it could be incorrectly promoted to a section. I mitigate this by requiring the number to match section-number format (dots, not standalone single digits at list depth), but a malformed document could still trick it. I'd catch this with a validation step that compares total node count against expected structure.

### 2. Where did you choose simplicity over correctness?

**Table extraction.** I format tables as plain text with pipe separators rather than preserving them as structured data in the database schema. This means table cells aren't individually addressable or diffable. In production, tables would need their own data model (row/column/cell) to properly detect "E3 response time changed from 2s to 1.5s." First thing that would break: staleness detection on a node whose only change is inside a table cell — the hash would change but the diff summary wouldn't pinpoint the specific cell.

### 3. Name one input you did not handle.

**A PDF with scanned image pages (no embedded text).** My parser relies on PyMuPDF's text extraction. If given a scanned document, it would extract empty text and produce a tree with only a root node and no children. The system wouldn't error — it would just return an empty tree, which is misleading. Detection: check if total extracted text length is below a minimum threshold relative to page count, and return a warning suggesting OCR is needed.
