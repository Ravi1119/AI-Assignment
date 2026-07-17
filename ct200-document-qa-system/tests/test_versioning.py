"""
Tests for document versioning and staleness detection.
Verifies that v1 -> v2 re-ingestion works correctly.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Document, DocumentVersion, DocumentNode
from app.ingestion import ingest_document, compare_versions

PDF_V1 = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..", "ct200_manual.pdf"
)
PDF_V2 = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..", "ct200_manual_v2.pdf"
)


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestVersioning:
    """Test document versioning behavior."""

    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        if not os.path.exists(PDF_V1) or not os.path.exists(PDF_V2):
            pytest.skip("PDF files not found")
        self.db = db_session

    def test_first_ingestion_creates_version_1(self):
        """First ingestion should create version 1."""
        version = ingest_document(
            self.db, PDF_V1, "ct200", "CT-200 Manual", "ct200_manual.pdf"
        )
        assert version.version_number == 1
        assert version.id == "ct200_v1"

    def test_second_ingestion_creates_version_2(self):
        """Second ingestion should create version 2 without destroying version 1."""
        v1 = ingest_document(
            self.db, PDF_V1, "ct200", "CT-200 Manual", "ct200_manual.pdf"
        )
        v2 = ingest_document(
            self.db, PDF_V2, "ct200", "CT-200 Manual", "ct200_manual_v2.pdf"
        )
        assert v1.version_number == 1
        assert v2.version_number == 2

        # Both versions' nodes should exist
        v1_nodes = self.db.query(DocumentNode).filter(
            DocumentNode.version_id == "ct200_v1"
        ).count()
        v2_nodes = self.db.query(DocumentNode).filter(
            DocumentNode.version_id == "ct200_v2"
        ).count()
        assert v1_nodes > 0
        assert v2_nodes > 0
        # V2 has more nodes (added section 5.3)
        assert v2_nodes > v1_nodes

    def test_version_comparison_detects_changes(self):
        """Comparing v1 and v2 should detect known changes."""
        ingest_document(self.db, PDF_V1, "ct200", "CT-200 Manual", "ct200_manual.pdf")
        ingest_document(self.db, PDF_V2, "ct200", "CT-200 Manual", "ct200_manual_v2.pdf")

        changes = compare_versions(self.db, "ct200", 1, 2)
        assert len(changes) > 0

        # Known changes between v1 and v2:
        # - Battery life changed (300 -> 250 cycles, 15% -> 10% threshold)
        # - Cuff inflation increment changed (40 -> 30 mmHg)
        # - E3 response time changed (2 seconds -> 1.5 seconds)
        # - New error code E6 added
        # - New section 5.3 (Data Export) added
        change_types = [c["type"] for c in changes]
        assert "modified" in change_types
        assert "added" in change_types

    def test_unchanged_nodes_have_same_hash(self):
        """Nodes that didn't change between v1 and v2 should have the same content hash."""
        ingest_document(self.db, PDF_V1, "ct200", "CT-200 Manual", "ct200_manual.pdf")
        ingest_document(self.db, PDF_V2, "ct200", "CT-200 Manual", "ct200_manual_v2.pdf")

        # Section 1.1 (Intended Use) is unchanged
        v1_node = (
            self.db.query(DocumentNode)
            .filter(DocumentNode.version_id == "ct200_v1", DocumentNode.section_number == "1.1")
            .first()
        )
        v2_node = (
            self.db.query(DocumentNode)
            .filter(DocumentNode.version_id == "ct200_v2", DocumentNode.section_number == "1.1")
            .first()
        )
        if v1_node and v2_node:
            assert v1_node.content_hash == v2_node.content_hash


class TestStalenessDetection:
    """Test that staleness detection works correctly."""

    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        if not os.path.exists(PDF_V1):
            pytest.skip("PDF files not found")
        self.db = db_session

    def test_node_not_stale_when_unchanged(self):
        """A node's content hash shouldn't change if re-parsed from the same file."""
        ingest_document(self.db, PDF_V1, "ct200", "CT-200 Manual", "ct200_manual.pdf")
        nodes = self.db.query(DocumentNode).filter(
            DocumentNode.version_id == "ct200_v1"
        ).all()
        # All nodes should have consistent hashes
        for node in nodes:
            recomputed = DocumentNode.compute_hash(node.heading, node.body_text)
            assert node.content_hash == recomputed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
