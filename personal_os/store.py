"""SQLite-Persistenzschicht fuer das Personal OS.

Eine Datei (``store.db``) im Datenverzeichnis enthaelt Wissens-Eintraege,
Loops, Delegationen und Key-Value-State (z. B. Connector-Cursors).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    hash TEXT UNIQUE,
    entities TEXT DEFAULT '[]',
    triplets TEXT DEFAULT '[]',
    embedding TEXT DEFAULT '[]',
    created_at TEXT DEFAULT '',
    meta TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS loops (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT DEFAULT 'open',
    priority INTEGER DEFAULT 1,
    due TEXT,
    repeat TEXT,
    next_action TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    created_at TEXT DEFAULT '',
    updated_at TEXT DEFAULT '',
    done_at TEXT,
    snooze_until TEXT,
    meta TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS delegations (
    id TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    instruction TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    result TEXT DEFAULT '',
    trace TEXT DEFAULT '[]',
    created_at TEXT DEFAULT '',
    updated_at TEXT DEFAULT '',
    meta TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT DEFAULT ''
);
"""

_WP1_SCHEMA = """
CREATE TABLE IF NOT EXISTS context_objects (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'private',
    status TEXT NOT NULL DEFAULT 'mentioned',
    confidence REAL DEFAULT 1.0,
    valid_from TEXT,
    valid_until TEXT,
    source TEXT DEFAULT '',
    source_item_id TEXT,
    created_by TEXT DEFAULT 'owner',
    superseded_by TEXT,
    history TEXT DEFAULT '[]',
    created_at TEXT DEFAULT '',
    updated_at TEXT DEFAULT '',
    meta TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS object_links (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    provenance TEXT DEFAULT '',
    created_at TEXT DEFAULT '',
    meta TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS permissions (
    subject TEXT NOT NULL,
    action TEXT NOT NULL,
    scope TEXT NOT NULL,
    effect TEXT NOT NULL DEFAULT 'allow',
    created_at TEXT DEFAULT '',
    meta TEXT DEFAULT '{}',
    PRIMARY KEY (subject, action, scope)
);
"""

_JSON_COLS = {
    "items": ["tags", "entities", "triplets", "embedding", "meta"],
    "loops": ["tags", "meta"],
    "delegations": ["trace", "meta"],
    "context_objects": ["history", "meta"],
    "object_links": ["meta"],
    "permissions": ["meta"],
}


class SQLiteStore:
    """duenner, thread-sicherer Zugriff auf die OS-Datenbank."""

    def __init__(self, data_dir: str):
        self.path = Path(data_dir) / "store.db"
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Additive Migration (WP1): Scope-Spalten + neue Tabellen, Daten bleiben."""
        for table in ("items", "loops"):
            cols = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            if "scope" not in cols:
                self.conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN scope TEXT NOT NULL "
                    "DEFAULT 'private'"
                )
        self.conn.executescript(_WP1_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def _row(self, table: str, row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        for col in _JSON_COLS.get(table, []):
            if col in data and isinstance(data[col], str):
                try:
                    data[col] = json.loads(data[col])
                except (ValueError, TypeError):
                    data[col] = []
        return data

    def _dump(self, table: str, data: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(data)
        for col in _JSON_COLS.get(table, []):
            if col in out and not isinstance(out[col], str):
                out[col] = json.dumps(out[col], ensure_ascii=False)
        return out

    def _insert(self, table: str, data: Dict[str, Any]) -> None:
        cols = self._dump(table, data)
        placeholders = ", ".join("?" for _ in cols)
        sql = (
            f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) "
            f"VALUES ({placeholders})"
        )
        self.conn.execute(sql, list(cols.values()))
        self.conn.commit()

    def _update(self, table: str, id_: str, fields: Dict[str, Any]) -> None:
        cols = self._dump(table, fields)
        sql = f"UPDATE {table} SET {', '.join(f'{c} = ?' for c in cols)} WHERE id = ?"
        self.conn.execute(sql, list(cols.values()) + [id_])
        self.conn.commit()

    def _get(self, table: str, id_: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            f"SELECT * FROM {table} WHERE id = ?", (id_,)
        ).fetchone()
        return self._row(table, row) if row else None

    def _list(
        self,
        table: str,
        where: str = "",
        params: tuple = (),
        order: str = "created_at DESC",
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        sql = f"SELECT * FROM {table}"
        if where:
            sql += f" WHERE {where}"
        sql += f" ORDER BY {order}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = self.conn.execute(sql, params).fetchall()
        return [self._row(table, r) for r in rows]

    def add_item(self, item: Dict[str, Any]) -> None:
        self._insert("items", item)

    def get_item(self, id_: str) -> Optional[Dict[str, Any]]:
        return self._get("items", id_)

    def find_item_by_hash(self, hash_: str) -> Optional[Dict[str, Any]]:
        rows = self._list("items", "hash = ?", (hash_,))
        return rows[0] if rows else None

    def list_items(
        self,
        kind: Optional[str] = None,
        since: Optional[str] = None,
        scope: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        where, params = [], []
        if kind:
            where.append("kind = ?")
            params.append(kind)
        if since:
            where.append("created_at >= ?")
            params.append(since)
        if scope is not None:
            where.append("scope = ?")
            params.append(scope)
        return self._list("items", " AND ".join(where), tuple(params), limit=limit)

    def count_items(self, since: Optional[str] = None) -> int:
        sql = "SELECT COUNT(*) AS c FROM items"
        params: tuple = ()
        if since:
            sql += " WHERE created_at >= ?"
            params = (since,)
        return int(self.conn.execute(sql, params).fetchone()["c"])

    def add_loop(self, loop: Dict[str, Any]) -> None:
        self._insert("loops", loop)

    def get_loop(self, id_: str) -> Optional[Dict[str, Any]]:
        return self._get("loops", id_)

    def update_loop(self, id_: str, fields: Dict[str, Any]) -> None:
        self._update("loops", id_, fields)

    def list_loops(
        self,
        status: Optional[str] = None,
        scope: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        where, params = [], []
        if status:
            where.append("status = ?")
            params.append("open" if status == "open" else status)
        if scope is not None:
            where.append("scope = ?")
            params.append(scope)
        return self._list(
            "loops",
            " AND ".join(where),
            tuple(params),
            order="priority DESC, due ASC",
            limit=limit,
        )

    def add_delegation(self, delegation: Dict[str, Any]) -> None:
        self._insert("delegations", delegation)

    def get_delegation(self, id_: str) -> Optional[Dict[str, Any]]:
        return self._get("delegations", id_)

    def update_delegation(self, id_: str, fields: Dict[str, Any]) -> None:
        self._update("delegations", id_, fields)

    def list_delegations(
        self, status: Optional[str] = None, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        where, params = "", ()
        if status:
            where, params = "status = ?", (status,)
        return self._list("delegations", where, params, limit=limit)

    def add_context_object(self, obj: Dict[str, Any]) -> None:
        self._insert("context_objects", obj)

    def get_context_object(self, id_: str) -> Optional[Dict[str, Any]]:
        return self._get("context_objects", id_)

    def update_context_object(self, id_: str, fields: Dict[str, Any]) -> None:
        self._update("context_objects", id_, fields)

    def list_context_objects(
        self,
        type_: Optional[str] = None,
        scope: Optional[str] = None,
        status: Optional[str] = None,
        include_superseded: bool = False,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        where, params = [], []
        if type_:
            where.append("type = ?")
            params.append(type_)
        if scope is not None:
            where.append("scope = ?")
            params.append(scope)
        if status:
            where.append("status = ?")
            params.append(status)
        if not include_superseded:
            where.append("superseded_by IS NULL")
        return self._list(
            "context_objects", " AND ".join(where), tuple(params), limit=limit
        )

    def add_object_link(self, link: Dict[str, Any]) -> None:
        self._insert("object_links", link)

    def list_links(self, object_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if object_id:
            return self._list(
                "object_links",
                "source_id = ? OR target_id = ?",
                (object_id, object_id),
            )
        return self._list("object_links")

    def add_permission(self, perm: Dict[str, Any]) -> None:
        self._insert("permissions", perm)

    def list_permissions(self, subject: Optional[str] = None) -> List[Dict[str, Any]]:
        if subject:
            return self._list("permissions", "subject = ?", (subject,))
        return self._list("permissions")

    def delete_permission(self, subject: str, action: str, scope: str) -> None:
        self.conn.execute(
            "DELETE FROM permissions WHERE subject = ? AND action = ? AND scope = ?",
            (subject, action, scope),
        )
        self.conn.commit()

    def kv_get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def kv_set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, value)
        )
        self.conn.commit()
