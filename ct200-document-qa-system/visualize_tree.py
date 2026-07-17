"""
Visualize the parsed PDF tree as JSON.
Run: python visualize_tree.py

Outputs:
  - tree_v1.json (hierarchical tree of ct200_manual.pdf)
  - tree_v2.json (hierarchical tree of ct200_manual_v2.pdf)
  - diff_v1_v2.json (what changed between versions)
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.parser import parse_pdf


def node_to_dict(node):
    """Convert ParsedNode to a dictionary for JSON output."""
    result = {
        "section_number": node.section_number or None,
        "heading": node.heading,
        "level": node.level,
        "content_hash": node.content_hash[:12] + "...",
        "body_text_preview": node.body_text[:150] + "..." if len(node.body_text) > 150 else node.body_text,
    }
    if node.children:
        result["children"] = [node_to_dict(child) for child in node.children]
    return result


def main():
    # Paths
    base = os.path.dirname(os.path.abspath(__file__))
    pdf_v1 = os.path.join(base, "data", "ct200_manual.pdf")
    pdf_v2 = os.path.join(base, "data", "ct200_manual_v2.pdf")

    if not os.path.exists(pdf_v1):
        pdf_v1 = os.path.join(base, "..", "ct200_manual.pdf")
    if not os.path.exists(pdf_v2):
        pdf_v2 = os.path.join(base, "..", "ct200_manual_v2.pdf")

    # Parse v1
    print("Parsing v1...")
    tree_v1 = parse_pdf(pdf_v1)
    v1_json = node_to_dict(tree_v1[0])

    with open("tree_v1.json", "w", encoding="utf-8") as f:
        json.dump(v1_json, f, indent=2, ensure_ascii=False)
    print(f"  Saved tree_v1.json")

    # Parse v2
    print("Parsing v2...")
    tree_v2 = parse_pdf(pdf_v2)
    v2_json = node_to_dict(tree_v2[0])

    with open("tree_v2.json", "w", encoding="utf-8") as f:
        json.dump(v2_json, f, indent=2, ensure_ascii=False)
    print(f"  Saved tree_v2.json")

    # Simple diff
    print("\nComparing v1 vs v2...")
    diff = compare_trees(tree_v1[0], tree_v2[0])

    with open("diff_v1_v2.json", "w", encoding="utf-8") as f:
        json.dump(diff, f, indent=2, ensure_ascii=False)
    print(f"  Saved diff_v1_v2.json")

    # Print tree to console
    print("\n" + "=" * 60)
    print("  CT-200 MANUAL v1 - DOCUMENT TREE")
    print("=" * 60)
    print_tree(tree_v1[0])

    print("\n" + "=" * 60)
    print("  CHANGES IN v2")
    print("=" * 60)
    for change in diff:
        status = change["status"].upper()
        section = change.get("section_number", "")
        heading = change["heading"]
        print(f"  [{status:8s}] {section:10s} {heading}")
        if change.get("summary"):
            print(f"             → {change['summary']}")


def print_tree(node, indent=0):
    """Print tree to console."""
    prefix = "  " * indent
    sec = f"[{node.section_number}]" if node.section_number else "[root]"
    print(f"{prefix}{sec} {node.heading}")
    for child in node.children:
        print_tree(child, indent + 1)


def compare_trees(root_v1, root_v2):
    """Compare two trees and return list of changes."""
    # Flatten both trees
    nodes_v1 = {}
    nodes_v2 = {}
    _flatten(root_v1, nodes_v1)
    _flatten(root_v2, nodes_v2)

    changes = []
    all_paths = set(nodes_v1.keys()) | set(nodes_v2.keys())

    for path in sorted(all_paths):
        n1 = nodes_v1.get(path)
        n2 = nodes_v2.get(path)

        if n1 and n2:
            if n1.content_hash != n2.content_hash:
                changes.append({
                    "status": "modified",
                    "section_number": n2.section_number,
                    "heading": n2.heading,
                    "summary": _summarize_change(n1, n2),
                })
        elif n1 and not n2:
            changes.append({
                "status": "removed",
                "section_number": n1.section_number,
                "heading": n1.heading,
            })
        elif n2 and not n1:
            changes.append({
                "status": "added",
                "section_number": n2.section_number,
                "heading": n2.heading,
            })

    return changes


def _flatten(node, result, path_prefix=""):
    """Flatten tree into {structural_path: node} dict."""
    path = node.structural_path
    result[path] = node
    for child in node.children:
        _flatten(child, result)


def _summarize_change(n1, n2):
    """Short summary of what changed."""
    if n1.heading != n2.heading:
        return f"Heading: '{n1.heading}' → '{n2.heading}'"
    # Find first line difference
    lines1 = n1.body_text.split("\n")
    lines2 = n2.body_text.split("\n")
    for i, (l1, l2) in enumerate(zip(lines1, lines2)):
        if l1 != l2:
            return f"Line {i+1} changed: '{l1[:60]}...' → '{l2[:60]}...'"
    if len(lines2) > len(lines1):
        return f"Added {len(lines2) - len(lines1)} new line(s)"
    return "Content changed"


if __name__ == "__main__":
    main()
