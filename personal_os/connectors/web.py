"""Web-Connector: URLs und RSS-Feeds ins Gedaechtnis laden."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple

from .base import Connector, ConnectorError

_TAG_RE = re.compile(r"<[^>]+>")


def fetch_text(url: str, timeout: int = 15) -> Tuple[str, str]:
    """holt eine URL und liefert (text, titel)."""
    try:
        import requests
    except ImportError as exc:
        raise ConnectorError("requests ist nicht installiert") from exc
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "personal-os/0.1"})
    resp.raise_for_status()
    html = resp.text
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        title = _TAG_RE.sub("", m.group(1)).strip()
    try:
        from bs4 import BeautifulSoup

        text = BeautifulSoup(html, "html.parser").get_text("\n")
    except ImportError:
        text = _TAG_RE.sub("\n", html)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, title or url


def parse_rss(xml_text: str) -> List[Dict[str, str]]:
    """Minimale RSS/Atom-Auswertung ohne Zusatzpakete."""
    items: List[Dict[str, str]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items
    for item in root.iter("item"):

        def _t(tag: str) -> str:
            el = item.find(tag)
            return (el.text or "").strip() if el is not None else ""

        link = _t("link")
        items.append(
            {
                "title": _t("title"),
                "link": link,
                "description": _t("description"),
            }
        )
    if not items:
        for entry in root.iter("entry"):
            title_el = entry.find("{http://www.w3.org/2005/Atom}title")
            link_el = entry.find("{http://www.w3.org/2005/Atom}link")
            summary_el = entry.find("{http://www.w3.org/2005/Atom}summary")
            items.append(
                {
                    "title": (
                        (title_el.text or "").strip() if title_el is not None else ""
                    ),
                    "link": link_el.get("href", "") if link_el is not None else "",
                    "description": (
                        (summary_el.text or "").strip()
                        if summary_el is not None
                        else ""
                    ),
                }
            )
    return items


class WebConnector(Connector):
    """Laedt konfigurierte URLs und RSS-Feeds (einmalig pro URL dedupliziert)."""

    name = "web"

    def sync(self) -> int:
        captured = 0
        for url in self.config.get("urls", []) or []:
            try:
                text, title = fetch_text(
                    url, timeout=int(self.config.get("timeout", 15))
                )
            except Exception:  # noqa: BLE001 - einzelner Feed stoppt den Sync nicht
                continue
            content = f"{title}\n\n{text}" if title else text
            item = self.core.capture(
                content,
                kind="web",
                source=url,
                meta={"title": title},
                scope=self.config.get("scope", "private"),
            )
            if not item.get("duplicate"):
                captured += 1
        for feed in self.config.get("rss", []) or []:
            try:
                import requests

                xml_text = requests.get(feed, timeout=15).text
            except Exception:  # noqa: BLE001
                continue
            for entry in parse_rss(xml_text)[
                : int(self.config.get("max_items_per_feed", 10))
            ]:
                content = f"{entry['title']}\n{entry['link']}\n\n{entry['description']}"
                item = self.core.capture(
                    content,
                    kind="rss",
                    source=entry["link"] or feed,
                    meta={"feed": feed},
                    scope=self.config.get("scope", "private"),
                )
                if not item.get("duplicate"):
                    captured += 1
        return captured
