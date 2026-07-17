"""
NoSQL store for LLM-generated test case outputs.

Supports MongoDB (preferred) with a JSON file fallback.
Each generation is linked to a selection and to the exact node content hashes
it was generated from, enabling staleness detection.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.config import MONGODB_URI, MONGODB_DB, JSON_STORE_PATH


class GenerationStore:
    """Abstract interface for storing generated test cases."""

    def save_generation(self, generation: dict) -> str:
        raise NotImplementedError

    def get_generation(self, generation_id: str) -> Optional[dict]:
        raise NotImplementedError

    def get_generations_by_selection(self, selection_id: str) -> list[dict]:
        raise NotImplementedError

    def get_generations_by_node(self, node_id: str) -> list[dict]:
        raise NotImplementedError

    def list_all_generations(self) -> list[dict]:
        raise NotImplementedError


class MongoGenerationStore(GenerationStore):
    """MongoDB-backed generation store."""

    def __init__(self):
        from pymongo import MongoClient
        self.client = MongoClient(MONGODB_URI)
        self.db = self.client[MONGODB_DB]
        self.collection = self.db["generations"]

    def save_generation(self, generation: dict) -> str:
        gen_id = generation.get("id") or str(uuid.uuid4())
        generation["id"] = gen_id
        generation["created_at"] = datetime.now(timezone.utc).isoformat()
        self.collection.insert_one(generation)
        return gen_id

    def get_generation(self, generation_id: str) -> Optional[dict]:
        result = self.collection.find_one({"id": generation_id}, {"_id": 0})
        return result

    def get_generations_by_selection(self, selection_id: str) -> list[dict]:
        results = self.collection.find({"selection_id": selection_id}, {"_id": 0})
        return list(results)

    def get_generations_by_node(self, node_id: str) -> list[dict]:
        results = self.collection.find(
            {"source_nodes.node_id": node_id}, {"_id": 0}
        )
        return list(results)

    def list_all_generations(self) -> list[dict]:
        results = self.collection.find({}, {"_id": 0})
        return list(results)


class JsonFileGenerationStore(GenerationStore):
    """JSON file-backed generation store (fallback when MongoDB unavailable)."""

    def __init__(self):
        self.path = JSON_STORE_PATH
        self._ensure_file()

    def _ensure_file(self):
        if not os.path.exists(self.path):
            with open(self.path, "w") as f:
                json.dump([], f)

    def _load(self) -> list[dict]:
        with open(self.path, "r") as f:
            return json.load(f)

    def _save(self, data: list[dict]):
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def save_generation(self, generation: dict) -> str:
        gen_id = generation.get("id") or str(uuid.uuid4())
        generation["id"] = gen_id
        generation["created_at"] = datetime.now(timezone.utc).isoformat()
        data = self._load()
        data.append(generation)
        self._save(data)
        return gen_id

    def get_generation(self, generation_id: str) -> Optional[dict]:
        data = self._load()
        for item in data:
            if item.get("id") == generation_id:
                return item
        return None

    def get_generations_by_selection(self, selection_id: str) -> list[dict]:
        data = self._load()
        return [item for item in data if item.get("selection_id") == selection_id]

    def get_generations_by_node(self, node_id: str) -> list[dict]:
        data = self._load()
        results = []
        for item in data:
            source_nodes = item.get("source_nodes", [])
            if any(sn.get("node_id") == node_id for sn in source_nodes):
                results.append(item)
        return results

    def list_all_generations(self) -> list[dict]:
        return self._load()


def get_generation_store() -> GenerationStore:
    """Factory: returns MongoDB store if available, else JSON file store."""
    if MONGODB_URI:
        try:
            store = MongoGenerationStore()
            # Test connection
            store.client.admin.command("ping")
            return store
        except Exception:
            pass
    return JsonFileGenerationStore()
