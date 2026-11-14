"""Langzeitgedaechtnis des Personal OS.

Jeder Capture landet hier: Entitaeten und Tripletts werden extrahiert, ein
lokales Hashing-Embedding berechnet und alles in SQLite abgelegt. Suche
kombiniert Cosine-Aehnlichkeit mit Keyword-Ueberlappung. Wenn ``semantica``
vollstaendig installiert ist, wird zusaetzlich ein Semantica-Knowledge-Graph
(``kg.json``) gepflegt, den Explorer/Exporter/MCP nutzen koennen.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from .extract import extract_entities, extract_triplets, tokenize
from .models import MemoryItem


class KnowledgeMemory:
    """Semantisches Gedaechtnis auf SQLite-Basis."""

    def __init__(self, store, config):
        self.store = store
        self.dim = int(getattr(config, "memory_dim", 256))
        self.kg_path = Path(config.data_dir) / "kg.json"
        self._kg = self._load_kg()

    def embed(self, text: str) -> List[float]:
        """Deterministisches Hashing-Embedding (Unigramme + Bigramme)."""
        vec = [0.0] * self.dim
        tokens = tokenize(text)
        grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        for gram in grams:
            digest = hashlib.sha256(gram.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [round(v / norm, 6) for v in vec]

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)) or 1.0
        nb = math.sqrt(sum(y * y for y in b)) or 1.0
        return dot / (na * nb)

    @staticmethod
    def _keyword_score(query_tokens: List[str], content: str) -> float:
        content_tokens = set(tokenize(content))
        if not query_tokens or not content_tokens:
            return 0.0
        overlap = sum(1 for t in set(query_tokens) if t in content_tokens)
        return overlap / math.sqrt(len(set(query_tokens)) * len(content_tokens))

    def add(self, item: MemoryItem) -> MemoryItem:
        """Eintrag anreichern (Entitaeten, Tripletts, Embedding) und speichern."""
        item.entities = extract_entities(item.content)
        item.triplets = extract_triplets(item.content)
        item.embedding = self.embed(item.content)
        if not item.hash:
            item.hash = hashlib.sha256(item.content.encode("utf-8")).hexdigest()
        self.store.add_item(item.to_dict())
        self._merge_into_kg(item)
        return item

    def search(
        self,
        query: str,
        limit: int = 5,
        kind: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Hybride Suche: 0.7 * Cosine + 0.3 * Keyword.

        ``scope`` filtert strikt: bei ``scope='work'`` werden private Eintraege
        niemals zurueckgegeben; ``scope=None`` ist die lokale Owner-Ansicht (alle).
        """
        q_emb = self.embed(query)
        q_tokens = tokenize(query)
        results = []
        for row in self.store.list_items(kind=kind, scope=scope):
            score = 0.7 * self._cosine(
                q_emb, row.get("embedding") or []
            ) + 0.3 * self._keyword_score(q_tokens, row.get("content", ""))
            results.append({**row, "score": round(score, 4)})
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

    def ask(
        self, query: str, limit: int = 5, scope: Optional[str] = None
    ) -> Dict[str, Any]:
        """Frage gegen das Gedaechtnis; liefert Treffer + verknuepfte Entitaeten."""
        results = self.search(query, limit=limit, scope=scope)
        related: List[Dict[str, Any]] = []
        for r in results:
            related.extend(self.related_entities(r.get("id"), scope=scope))
        seen, uniq = set(), []
        for e in related:
            key = (e.get("type"), str(e.get("id")).lower())
            if key not in seen:
                seen.add(key)
                uniq.append(e)
        return {"query": query, "results": results, "related_entities": uniq[:10]}

    def related_entities(
        self, item_id: str, scope: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Entitaeten, die im KG mit den Entitaeten eines Eintrags verknuepft sind.

        Bei ``scope`` werden nur Entitaeten geliefert, die auch in Eintraegen
        desselben Scopes vorkommen (der KG ist global; private Entitaeten duerfen
        nicht ueber Work-Ergebnisse durchsickern).
        """
        item = self.store.get_item(item_id)
        if not item:
            return []
        ids = {str(e.get("id")).lower() for e in item.get("entities", [])}
        allowed: Optional[set] = None
        if scope is not None:
            allowed = set()
            for row in self.store.list_items(scope=scope):
                allowed.update(
                    str(e.get("id")).lower() for e in row.get("entities", [])
                )
        out = []
        for rel in self._kg.get("relationships", []):
            src = str(rel.get("source", "")).lower()
            tgt = str(rel.get("target", "")).lower()
            if src in ids and tgt not in ids:
                if allowed is not None and tgt not in allowed:
                    continue
                out.append(
                    {"id": rel.get("target"), "type": "entity", "via": rel.get("type")}
                )
            elif tgt in ids and src not in ids:
                if allowed is not None and src not in allowed:
                    continue
                out.append(
                    {"id": rel.get("source"), "type": "entity", "via": rel.get("type")}
                )
        return out

    def stats(self) -> Dict[str, Any]:
        return {
            "items": self.store.count_items(),
            "entities": len(self._kg.get("entities", [])),
            "relationships": len(self._kg.get("relationships", [])),
        }

    def _load_kg(self) -> Dict[str, Any]:
        if self.kg_path.exists():
            try:
                return json.loads(self.kg_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                pass
        return {
            "entities": [],
            "relationships": [],
            "metadata": {"backend": "personal_os"},
        }

    def _save_kg(self) -> None:
        self.kg_path.write_text(
            json.dumps(self._kg, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _merge_into_kg(self, item: MemoryItem) -> None:
        entities = self._kg.setdefault("entities", [])
        relationships = self._kg.setdefault("relationships", [])
        known = {str(e.get("id")).lower() for e in entities}
        for e in item.entities:
            if str(e.get("id")).lower() not in known:
                known.add(str(e.get("id")).lower())
                entities.append({**e, "source_item": item.id})
        for t in item.triplets:
            rel = {
                "source": t["subject"],
                "target": t["object"],
                "type": t["predicate"],
                "source_item": item.id,
            }
            relationships.append(rel)
        self._kg.setdefault("metadata", {})["last_item"] = item.id
        self._save_kg()
