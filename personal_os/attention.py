"""WP2: Attention Engine — deterministische, erklaerbare Aufmerksamkeitsbewertung.

Bewertet Kontextobjekte (inkl. Commitments) und offene Loops. Keine
Statusaenderungen, kein LLM, keine eigenen Entscheidungen. Jede Bewertung liefert
Score + Faktoren + Grund + Quellen + Zeitpunkt + fehlende Informationen (A2).

Gewichtung (explizit, dokumentiert):
  Dringlichkeit: ueberfaellig 30 + 5/Tag (max 7 Tage) | heute 30 | <=3d 18 | <=7d 10
  Verbindlichkeit: committed +25 | intent +10 | mentioned +5
  Kontext (nur vorhandene Links): blocks/blocked_by/depends_on +15 | goal_of/
  part_of/works_on/related_to +10
  Stale (keine Frist, lange nicht bearbeitet): +10
  Konfidenz reduziert NIEMALS den Score — niedrige Konfidenz erzeugt
  Klaerungsbedarf (Kategorie), keine Abwertung (A1).
Kategorie: action (Handlungsbedarf) / clarification (Klaerungsbedarf) / observe.
Prioritaet: score >= 60 -> p1, >= 35 -> p2, sonst p3.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .models import utcnow

BLOCK_RELATIONS = {"blocks", "blocked_by", "depends_on"}
CONTEXT_RELATIONS = {"goal_of", "part_of", "works_on", "related_to", "assigned_to"}

WEIGHTS = {
    "overdue_base": 30,
    "overdue_per_day": 5,
    "overdue_max_days": 7,
    "due_today": 30,
    "due_3d": 18,
    "due_7d": 10,
    "committed": 25,
    "intent": 10,
    "mentioned": 5,
    "blocked": 15,
    "context_link": 10,
    "stale": 10,
}

PRIORITY_THRESHOLDS = {"p1": 60, "p2": 35}

TYPE_IMPORTANCE = {"goal": 15, "project": 10, "area": 5}
SNOOZE_REPEAT_MIN = 2
SNOOZE_REPEAT_POINTS = 5
EVAL_KEEP_PER_OBJECT = 10


def _norm_title(title: str) -> str:
    low = " ".join((title or "").lower().split())
    for filler in ("ich ", "mir ", "dir ", "den ", "die ", "das ", "ein ", "eine "):
        if low.startswith(filler):
            low = low[len(filler) :]
    return low


def _days_overdue(due: str, today: str) -> int:
    try:
        return (datetime.fromisoformat(today) - datetime.fromisoformat(due)).days
    except ValueError:
        return 0


class AttentionEngine:
    """Read-only Bewertungsschicht ueber Kontextmodell + Loops."""

    def __init__(self, core):
        self.core = core

    def evaluate(
        self,
        now: Optional[datetime] = None,
        scope: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Bewertet alle relevanten offenen Objekte; liefert erklaerbare Items."""
        now = now or datetime.now()
        store = self.core.store
        today = now.date().isoformat()
        stale_threshold = (
            (now - timedelta(days=self.core.config.adhd.stale_days)).date().isoformat()
        )

        candidates: List[Dict[str, Any]] = []
        for obj in self.core.context.list(scope=scope):
            if obj["status"] in ("done", "rejected"):
                continue
            candidates.append({"kind": "object", "ref": obj})
        for lp in self.core.loops.list("open", scope=scope):
            if lp.get("snooze_until") and lp["snooze_until"] > today:
                continue
            candidates.append(
                {
                    "kind": "loop",
                    "ref": {
                        "id": lp["id"],
                        "type": "task",
                        "title": lp["title"],
                        "scope": lp.get("scope", "private"),
                        "status": "committed",
                        "confidence": 1.0,
                        "source": "loop",
                        "source_item_id": None,
                        "meta": {
                            "due": lp.get("due"),
                            "responsible": None,
                            "snooze_count": (lp.get("meta") or {}).get(
                                "snooze_count", 0
                            ),
                        },
                        "updated_at": lp.get("updated_at", ""),
                        "valid_until": None,
                    },
                }
            )

        links_by_obj: Dict[str, List[Dict[str, Any]]] = {}
        for link in store.list_links():
            links_by_obj.setdefault(link["source_id"], []).append(link)
            links_by_obj.setdefault(link["target_id"], []).append(link)

        items: List[Dict[str, Any]] = []
        for cand in candidates:
            item = self._score(
                cand["ref"], cand["kind"], links_by_obj, store, today, stale_threshold
            )
            if item:
                items.append(item)

        merged = self._dedup(items)
        merged.sort(
            key=lambda i: (-i["score"], i.get("due") or "9999-12-31", i["object_id"])
        )
        if limit:
            merged = merged[:limit]
        evaluated_at = utcnow()
        for item in merged:
            item["evaluated_at"] = evaluated_at
            store.add_attention_eval(
                {
                    "id": f"{item['object_id']}:{evaluated_at}:{item['score']}",
                    "evaluated_at": evaluated_at,
                    "scope": item["scope"],
                    "object_id": item["object_id"],
                    "object_type": item["object_type"],
                    "score": item["score"],
                    "priority": item["priority"],
                    "category": item["category"],
                    "factors": item["factors"],
                    "reason": item["reason"],
                    "sources": item["sources"],
                    "missing_info": item["missing_info"],
                }
            )
            store.prune_attention_evals(item["object_id"], keep=EVAL_KEEP_PER_OBJECT)
        return {
            "evaluated_at": evaluated_at,
            "scope": scope,
            "items": merged,
            "counts": {
                "action": sum(1 for i in merged if i["category"] == "action"),
                "clarification": sum(
                    1 for i in merged if i["category"] == "clarification"
                ),
                "observe": sum(1 for i in merged if i["category"] == "observe"),
            },
        }

    def _score(
        self,
        obj: Dict[str, Any],
        kind: str,
        links_by_obj: Dict[str, List[Dict[str, Any]]],
        store,
        today: str,
        stale_threshold: str,
    ) -> Optional[Dict[str, Any]]:
        factors: Dict[str, int] = {}
        reasons: List[str] = []
        missing: List[str] = []
        meta = obj.get("meta") or {}
        due = meta.get("due") or obj.get("due")
        status = obj.get("status", "mentioned")
        confidence = float(obj.get("confidence", 1.0))

        obj_type = obj.get("type", kind)
        if obj_type in TYPE_IMPORTANCE:
            factors["importance"] = TYPE_IMPORTANCE[obj_type]
            reasons.append(
                f"langfristig wichtig (Typ '{obj_type}', +{TYPE_IMPORTANCE[obj_type]})"
            )

        if due:
            if due < today:
                days = _days_overdue(due, today)
                pts = (
                    WEIGHTS["overdue_base"]
                    + min(days, WEIGHTS["overdue_max_days"])
                    * WEIGHTS["overdue_per_day"]
                )
                factors["overdue"] = pts
                reasons.append(f"überfällig seit {days} Tag(en) (+{pts})")
            elif due == today:
                factors["due_today"] = WEIGHTS["due_today"]
                reasons.append(f"heute fällig (+{WEIGHTS['due_today']})")
            elif (
                due
                <= (datetime.fromisoformat(today) + timedelta(days=3))
                .date()
                .isoformat()
            ):
                factors["due_soon"] = WEIGHTS["due_3d"]
                reasons.append(f"fällig bis {due} (+{WEIGHTS['due_3d']})")
            elif (
                due
                <= (datetime.fromisoformat(today) + timedelta(days=7))
                .date()
                .isoformat()
            ):
                factors["due_7d"] = WEIGHTS["due_7d"]
                reasons.append(f"fällig innerhalb 7 Tage (+{WEIGHTS['due_7d']})")
        elif status in ("committed", "intent") and obj_type == "commitment":
            missing.append("keine Frist hinterlegt")

        if status in WEIGHTS and status in ("committed", "intent", "mentioned"):
            factors[f"status_{status}"] = WEIGHTS[status]
            reasons.append(f"Status '{status}' (+{WEIGHTS[status]})")

        if confidence < 0.7:
            missing.append(f"geringe Erkennungskonfidenz ({confidence})")

        if not meta.get("responsible") and obj.get("type") == "commitment":
            missing.append("keine verantwortliche Person")

        for link in links_by_obj.get(obj["id"], []):
            other_id = (
                link["target_id"]
                if link["source_id"] == obj["id"]
                else link["source_id"]
            )
            other = store.get_context_object(other_id)
            if not other or other.get("superseded_by"):
                continue
            rel = link["relation"]
            if rel in BLOCK_RELATIONS and other.get("status") in (
                "committed",
                "intent",
                "mentioned",
            ):
                factors["blocked"] = factors.get("blocked", 0) + WEIGHTS["blocked"]
                reasons.append(
                    f"hängt mit '{other.get('title')}' zusammen "
                    f"({rel}, +{WEIGHTS['blocked']})"
                )
            elif rel in CONTEXT_RELATIONS:
                factors["context_link"] = (
                    factors.get("context_link", 0) + WEIGHTS["context_link"]
                )
                reasons.append(
                    f"verknüpft mit '{other.get('title')}' "
                    f"({rel}, +{WEIGHTS['context_link']})"
                )

        updated = (obj.get("updated_at") or obj.get("created_at") or "")[:10]
        if not due and updated and updated < stale_threshold:
            factors["stale"] = WEIGHTS["stale"]
            reasons.append(f"seit {updated} nicht bearbeitet (+{WEIGHTS['stale']})")
            missing.append("lange nicht bearbeitet")

        snooze_count = int((obj.get("meta") or {}).get("snooze_count", 0) or 0)
        if snooze_count >= SNOOZE_REPEAT_MIN:
            factors["snooze_repeat"] = SNOOZE_REPEAT_POINTS
            reasons.append(
                f"wiederholt verschoben ({snooze_count}x, +{SNOOZE_REPEAT_POINTS})"
            )

        score = sum(factors.values())
        category = "observe"
        if (
            factors.get("overdue")
            or factors.get("due_today")
            or (
                status == "committed"
                and (factors.get("due_soon") or factors.get("due_7d"))
            )
        ):
            category = "action"
        if missing:
            category = "clarification" if category == "observe" else category
            if category == "observe":
                category = "clarification"
        if score < 5:
            return None
        priority = (
            "p1"
            if score >= PRIORITY_THRESHOLDS["p1"]
            else ("p2" if score >= PRIORITY_THRESHOLDS["p2"] else "p3")
        )
        return {
            "object_id": obj["id"],
            "object_type": obj_type,
            "title": obj.get("title", ""),
            "scope": obj.get("scope", "private"),
            "status": status,
            "due": due,
            "score": score,
            "priority": priority,
            "category": category,
            "factors": factors,
            "reason": "; ".join(reasons) if reasons else "allgemein relevant",
            "sources": [s for s in (obj.get("source"), obj.get("source_item_id")) if s],
            "missing_info": missing,
            "confidence": confidence,
        }

    def _dedup(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Dasselbe Thema (normierter Titel + Scope) erscheint nur einmal."""
        best: Dict[tuple, Dict[str, Any]] = {}
        for item in items:
            key = (item["scope"], _norm_title(item["title"]))
            if key not in best or item["score"] > best[key]["score"]:
                best[key] = item
        return list(best.values())
