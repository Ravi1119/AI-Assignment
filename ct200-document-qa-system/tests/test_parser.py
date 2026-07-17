"""
Unit tests for the PDF parser, targeting structural irregularities in the CT-200 manual.

Tests the three explicit edge cases required by the assignment:
1. Out-of-order sections (3.4 appears before 3.3) - both must be preserved as siblings
2. Level jumps (2.1 -> 2.1.1.1 skipping intermediate levels) - correct parent assignment
3. Duplicate headings (Error Codes in 4.2 and 7.1) - distinct IDs with correct parents
"""

import os
import sys
import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.parser import parse_pdf, _determine_level, _find_parent, ParsedNode, generate_node_id


# Path to the test PDF
PDF_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..", "ct200_manual.pdf"
)


class TestLevelDetermination:
    """Test the level determination from section numbers."""

    def test_single_number(self):
        assert _determine_level("1") == 1
        assert _determine_level("8") == 1

    def test_two_parts(self):
        assert _determine_level("1.1") == 2
        assert _determine_level("3.4") == 2

    def test_three_parts(self):
        assert _determine_level("2.1.1") == 3

    def test_four_parts(self):
        assert _determine_level("2.1.1.1") == 4

    def test_empty(self):
        assert _determine_level("") == 0


class TestParserWithRealPDF:
    """Integration tests using the actual CT-200 manual PDF."""

    @pytest.fixture(autouse=True)
    def setup(self):
        if not os.path.exists(PDF_PATH):
            pytest.skip(f"PDF not found at {PDF_PATH}")
        self.tree = parse_pdf(PDF_PATH)
        self.root = self.tree[0]
        # Flatten all nodes for easier searching
        self.all_nodes = []
        self._flatten(self.root)

    def _flatten(self, node):
        self.all_nodes.append(node)
        for child in node.children:
            self._flatten(child)

    def _find_by_section(self, section_number: str) -> ParsedNode:
        for n in self.all_nodes:
            if n.section_number == section_number:
                return n
        raise ValueError(f"Section {section_number} not found")

    # --- Test 1: Out-of-order sections (3.4 before 3.3) ---
    def test_out_of_order_sections_both_exist(self):
        """Sections 3.4 and 3.3 must both exist even though 3.4 appears first in the PDF."""
        section_34 = self._find_by_section("3.4")
        section_33 = self._find_by_section("3.3")
        assert section_34 is not None
        assert section_33 is not None
        assert section_34.heading == "Auto Shutoff" or "Auto" in section_34.heading
        assert section_33.heading == "Result Display and Classification" or "Result" in section_33.heading

    def test_out_of_order_sections_same_parent(self):
        """3.4 and 3.3 are both children of section 3, regardless of document order."""
        section_34 = self._find_by_section("3.4")
        section_33 = self._find_by_section("3.3")
        section_3 = self._find_by_section("3")
        assert section_34.parent == section_3
        assert section_33.parent == section_3

    # --- Test 2: Level jump (2.1 -> 2.1.1.1) ---
    def test_level_jump_correct_parent(self):
        """
        Section 2.1.1.1 (Battery Life) jumps directly from 2.1 without a 2.1.1.
        It must be a descendant of 2.1, not of 2 or root.
        """
        section_21 = self._find_by_section("2.1")
        section_2111 = self._find_by_section("2.1.1.1")
        assert section_2111 is not None
        assert "Battery" in section_2111.heading
        # 2.1.1.1 should be a child of 2.1 (its nearest valid ancestor)
        assert section_2111.parent == section_21

    def test_level_jump_correct_level(self):
        """2.1.1.1 must have level 4, not level 3."""
        section_2111 = self._find_by_section("2.1.1.1")
        assert section_2111.level == 4

    # --- Test 3: Duplicate headings produce distinct nodes ---
    def test_duplicate_heading_error_codes_distinct_ids(self):
        """
        'Error Codes' appears in both section 4.2 and 7.1.
        They must produce two distinct node IDs.
        """
        section_42 = self._find_by_section("4.2")
        section_71 = self._find_by_section("7.1")
        assert section_42.heading == "Error Codes"
        assert section_71.heading == "Error Codes"
        # Generate IDs to verify they're distinct
        id_42 = generate_node_id("test_v1", "4.2", "Error Codes", section_42.order_index)
        id_71 = generate_node_id("test_v1", "7.1", "Error Codes", section_71.order_index)
        assert id_42 != id_71

    def test_duplicate_heading_error_codes_correct_parents(self):
        """
        4.2 Error Codes is under section 4 (Alarms and Safety Behavior).
        7.1 Error Codes is under section 7 (Troubleshooting).
        """
        section_42 = self._find_by_section("4.2")
        section_71 = self._find_by_section("7.1")
        section_4 = self._find_by_section("4")
        section_7 = self._find_by_section("7")
        assert section_42.parent == section_4
        assert section_71.parent == section_7

    # --- Additional structural tests ---
    def test_root_has_title(self):
        """Root node should capture the document title."""
        assert "CardioTrack" in self.root.heading or "CT-200" in self.root.heading

    def test_top_level_sections_count(self):
        """The manual has 8 top-level sections."""
        top_level = [n for n in self.root.children if n.level == 1]
        assert len(top_level) == 8

    def test_all_sections_have_content_hash(self):
        """Every node must have a non-empty content hash."""
        for node in self.all_nodes:
            assert node.content_hash, f"Node {node.section_number} has no content hash"


class TestNodeIdGeneration:
    """Test that node ID generation produces stable, unique IDs."""

    def test_same_input_same_id(self):
        """Same inputs produce the same ID (deterministic)."""
        id1 = generate_node_id("v1", "4.2", "Error Codes", 0)
        id2 = generate_node_id("v1", "4.2", "Error Codes", 0)
        assert id1 == id2

    def test_different_section_different_id(self):
        """Different section numbers produce different IDs."""
        id1 = generate_node_id("v1", "4.2", "Error Codes", 0)
        id2 = generate_node_id("v1", "7.1", "Error Codes", 0)
        assert id1 != id2

    def test_different_version_different_id(self):
        """Same node in different versions gets different IDs."""
        id1 = generate_node_id("v1", "3.2", "Cuff Inflation", 0)
        id2 = generate_node_id("v2", "3.2", "Cuff Inflation", 0)
        assert id1 != id2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
