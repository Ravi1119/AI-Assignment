"""
PDF parser that extracts hierarchical document structure from the CT-200 manual.

Handles structural irregularities:
- Out-of-order section numbering (3.4 before 3.3)
- Level jumps (2.1 -> 2.1.1.1 skipping intermediate levels)
- Duplicate heading text across different sections (e.g., "Error Codes" in 4.2 and 7.1)
- Tables embedded in content
"""

import re
import uuid
import hashlib
from dataclasses import dataclass, field
from typing import Optional

import fitz  # PyMuPDF
import pdfplumber


@dataclass
class ParsedNode:
    """Intermediate representation of a document node during parsing."""
    heading: str
    level: int
    section_number: str
    body_text: str = ""
    children: list = field(default_factory=list)
    parent: Optional["ParsedNode"] = None
    order_index: int = 0

    @property
    def content_hash(self) -> str:
        content = f"{self.heading.strip()}\n{self.body_text.strip()}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @property
    def structural_path(self) -> str:
        """Build a path from root to this node using section numbers."""
        parts = []
        node = self
        while node:
            parts.append(node.section_number or node.heading)
            node = node.parent
        parts.reverse()
        return "/".join(parts)


def _determine_level(section_number: str) -> int:
    """
    Determine the heading level from a section number.
    
    '1' -> level 1
    '1.1' -> level 2
    '2.1.1.1' -> level 4
    
    Note: We determine level from the actual number of dots/parts,
    NOT from whether intermediate levels exist. This correctly handles
    the 2.1 -> 2.1.1.1 jump in the CT-200 manual.
    """
    if not section_number:
        return 0
    parts = section_number.split(".")
    return len(parts)


def _find_parent(node_level: int, section_number: str, stack: list[ParsedNode]) -> Optional[ParsedNode]:
    """
    Find the correct parent for a new node based on level hierarchy.
    
    Uses a stack-based approach: walk back up the stack until we find
    a node whose level is strictly less than the new node's level.
    This correctly handles out-of-order sections (3.4 before 3.3)
    and level jumps (2.1 -> 2.1.1.1).
    """
    while stack and stack[-1].level >= node_level:
        stack.pop()
    if stack:
        return stack[-1]
    return None


# Regex for section headings.
# Matches formats like:
#   "1. Device Overview"        -> section_number="1", heading="Device Overview"
#   "1.1 Intended Use"          -> section_number="1.1", heading="Intended Use"
#   "2.1.1.1 Battery Life..."   -> section_number="2.1.1.1", heading="Battery Life..."
# The optional trailing period handles "N. Title" format used for top-level sections.
HEADING_PATTERN = re.compile(
    r"^(\d+(?:\.\d+)*)\.?\s+(.+)$"
)

# Pattern for table rows (Key-Value pairs on adjacent lines)
TABLE_HEADER_KEYWORDS = {"Parameter", "Code", "Meaning", "Device Behavior", "Value"}


def extract_tables_from_page(pdf_path: str, page_num: int) -> list[dict]:
    """Extract tables from a specific page using pdfplumber."""
    tables = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_num < len(pdf.pages):
                page = pdf.pages[page_num]
                page_tables = page.extract_tables()
                for table in page_tables:
                    if table and len(table) > 1:
                        headers = [cell.strip() if cell else "" for cell in table[0]]
                        rows = []
                        for row in table[1:]:
                            rows.append([cell.strip() if cell else "" for cell in row])
                        tables.append({"headers": headers, "rows": rows})
    except Exception:
        pass
    return tables


def _format_table_as_text(table: dict) -> str:
    """Format a table dict as readable text."""
    lines = []
    headers = table["headers"]
    lines.append(" | ".join(headers))
    lines.append("-" * len(lines[0]))
    for row in table["rows"]:
        lines.append(" | ".join(row))
    return "\n".join(lines)


def parse_pdf(pdf_path: str) -> list[ParsedNode]:
    """
    Parse a PDF document into a hierarchical tree of nodes.
    
    Returns a list of top-level nodes (the roots of the tree).
    Each node may contain children, forming the full hierarchy.
    """
    doc = fitz.open(pdf_path)

    # Step 1: Extract all text blocks with their page numbers
    all_lines = []
    for page_num in range(len(doc)):
        text = doc[page_num].get_text()
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped:
                all_lines.append((stripped, page_num))

    # Step 2: Identify the document title (first non-empty content before first numbered heading)
    title_parts = []
    first_heading_idx = 0
    for i, (line, _) in enumerate(all_lines):
        if HEADING_PATTERN.match(line):
            first_heading_idx = i
            break
        title_parts.append(line)

    doc_title = " ".join(title_parts).strip()

    # Create root node for the document title
    root = ParsedNode(
        heading=doc_title,
        level=0,
        section_number="",
        order_index=0,
    )

    # Step 3: Parse sections
    nodes_flat: list[ParsedNode] = []  # All nodes in document order
    stack: list[ParsedNode] = [root]  # Stack for parent tracking
    current_node: Optional[ParsedNode] = root
    current_body_lines: list[str] = []

    # Track tables by page for extraction
    tables_by_page: dict[int, list[dict]] = {}

    def flush_body():
        """Save accumulated body lines to the current node."""
        nonlocal current_body_lines
        if current_node and current_body_lines:
            body = "\n".join(current_body_lines).strip()
            current_node.body_text = body
        current_body_lines = []

    # Track seen section numbers to detect list items masquerading as headings
    seen_sections: set[str] = set()

    for i in range(first_heading_idx, len(all_lines)):
        line, page_num = all_lines[i]
        match = HEADING_PATTERN.match(line)

        if match:
            section_num = match.group(1)
            heading_text = match.group(2).strip()
            level = _determine_level(section_num)

            # Heuristic to detect numbered list items vs real section headings:
            # A numbered list item (e.g., "1. Normal: systolic < 120") is treated as body
            # text if it would create a duplicate top-level section AND contains ":"
            # immediately, or if the "heading" text looks like a list description.
            is_list_item = False
            if level == 1 and section_num in seen_sections:
                # Duplicate section number at top level = likely a numbered list
                is_list_item = True
            elif level == 1 and ":" in heading_text and len(heading_text.split()) > 3:
                # Top-level "heading" with colon and long text = likely list item
                # e.g., "1. Normal: systolic < 120 and diastolic < 80"
                is_list_item = True

            if is_list_item:
                current_body_lines.append(line)
                continue

            # Flush body text of previous node
            flush_body()

            seen_sections.add(section_num)

            new_node = ParsedNode(
                heading=heading_text,
                level=level,
                section_number=section_num,
            )

            # Find parent using stack
            parent = _find_parent(level, section_num, stack)
            if parent is None:
                parent = root

            new_node.parent = parent
            new_node.order_index = len(parent.children)
            parent.children.append(new_node)

            nodes_flat.append(new_node)
            stack.append(new_node)
            current_node = new_node
        else:
            # Accumulate body text
            current_body_lines.append(line)

    # Flush the last node's body
    flush_body()

    # Step 4: Extract tables and attach to relevant nodes
    for page_num in range(len(doc)):
        tables = extract_tables_from_page(pdf_path, page_num)
        if tables:
            tables_by_page[page_num] = tables

    # Attach tables to nodes by matching page context
    # We re-scan to find which nodes are on which pages
    _attach_tables_to_nodes(doc, nodes_flat, tables_by_page, pdf_path)

    doc.close()
    return [root]


def _attach_tables_to_nodes(doc, nodes_flat, tables_by_page, pdf_path):
    """
    Attach extracted tables to the correct nodes.
    Uses heading proximity on the same page to determine which node owns a table.
    """
    if not tables_by_page:
        return

    # Build a map of which page each node's heading appears on
    # Use index into nodes_flat as key since ParsedNode is unhashable (mutable list fields)
    node_page_map: dict[int, int] = {}  # index in nodes_flat -> page_num
    for page_num in range(len(doc)):
        page_text = doc[page_num].get_text()
        for idx, node in enumerate(nodes_flat):
            if idx not in node_page_map and node.heading in page_text:
                node_page_map[idx] = page_num

    # For each page with tables, find the node whose heading appears
    # on that page (or the immediately preceding page) and whose content
    # seems to relate to table data
    for page_num, tables in tables_by_page.items():
        # Find candidate node indices on this page
        candidates = [idx for idx, p in node_page_map.items() if p == page_num]
        if not candidates:
            # Try the previous page (table headers might be on prior page)
            candidates = [idx for idx, p in node_page_map.items() if p == page_num - 1]

        for table in tables:
            table_text = _format_table_as_text(table)
            if candidates:
                # Attach to the most recent candidate (last in document order)
                best_idx = max(candidates)
                best = nodes_flat[best_idx]
                if table_text not in (best.body_text or ""):
                    # Append table if not already captured in body
                    if best.body_text:
                        best.body_text += "\n\n[TABLE]\n" + table_text
                    else:
                        best.body_text = "[TABLE]\n" + table_text


def generate_node_id(version_id: str, section_number: str, heading: str, order: int) -> str:
    """
    Generate a stable, unique node ID.
    
    Uses version + section number + heading to create reproducible IDs.
    This ensures that:
    - Duplicate headings (like "Error Codes") get distinct IDs because their section numbers differ
    - Re-parsing the same document produces the same IDs
    """
    raw = f"{version_id}:{section_number}:{heading}:{order}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]
