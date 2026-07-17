"""SQLAlchemy ORM models for the document tree."""

import hashlib
from sqlalchemy import Column, String, Integer, Text, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.database import Base


class Document(Base):
    """A document (e.g., ct200_manual) that can have multiple versions."""
    __tablename__ = "documents"

    id = Column(String, primary_key=True)  # e.g. "ct200_manual"
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    versions = relationship("DocumentVersion", back_populates="document", order_by="DocumentVersion.version_number")


class DocumentVersion(Base):
    """A specific version of a document."""
    __tablename__ = "document_versions"

    id = Column(String, primary_key=True)  # e.g. "ct200_manual_v1"
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    version_number = Column(Integer, nullable=False)
    source_filename = Column(String, nullable=False)
    ingested_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    document = relationship("Document", back_populates="versions")
    nodes = relationship("DocumentNode", back_populates="version", cascade="all, delete-orphan")


class DocumentNode(Base):
    """A single node in the document hierarchy tree."""
    __tablename__ = "document_nodes"

    id = Column(String, primary_key=True)  # Unique node ID
    version_id = Column(String, ForeignKey("document_versions.id"), nullable=False)
    heading = Column(String, nullable=False)
    level = Column(Integer, nullable=False)  # 0 = root/title, 1 = section, 2 = subsection, etc.
    section_number = Column(String, nullable=True)  # e.g. "3.2", "4.2"
    body_text = Column(Text, nullable=False, default="")
    content_hash = Column(String, nullable=False)  # SHA-256 of heading + body_text
    parent_id = Column(String, ForeignKey("document_nodes.id"), nullable=True)
    order_index = Column(Integer, nullable=False, default=0)  # Position among siblings

    # Stable path for cross-version matching (e.g., "1/1.1" or "4/4.2")
    structural_path = Column(String, nullable=False, default="")

    version = relationship("DocumentVersion", back_populates="nodes")
    parent = relationship("DocumentNode", remote_side=[id], backref="children")

    @staticmethod
    def compute_hash(heading: str, body_text: str) -> str:
        """Compute content hash from heading and body text."""
        content = f"{heading.strip()}\n{body_text.strip()}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


class Selection(Base):
    """A named selection of node IDs, pinned to specific versions."""
    __tablename__ = "selections"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    items = relationship("SelectionItem", back_populates="selection", cascade="all, delete-orphan")


class SelectionItem(Base):
    """A single node reference within a selection, version-pinned."""
    __tablename__ = "selection_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    selection_id = Column(String, ForeignKey("selections.id"), nullable=False)
    node_id = Column(String, ForeignKey("document_nodes.id"), nullable=False)
    version_id = Column(String, ForeignKey("document_versions.id"), nullable=False)
    content_hash_at_selection = Column(String, nullable=False)  # Hash when selected

    selection = relationship("Selection", back_populates="items")
    node = relationship("DocumentNode")
