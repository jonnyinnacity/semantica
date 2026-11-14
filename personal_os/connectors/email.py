"""E-Mail-Connector: ungelesene Mails per IMAP ins OS (Zugangsdaten nur via Env)."""

from __future__ import annotations

import imaplib
import os
from email import message_from_bytes
from email.header import decode_header, make_header
from typing import Any, Dict

from .base import Connector, ConnectorError


def _cfg(config: Dict[str, Any], key: str, env: str) -> str:
    val = config.get(key) or os.environ.get(env, "")
    return str(val)


def _decode_subject(msg) -> str:
    raw = msg.get("Subject", "")
    try:
        return str(make_header(decode_header(raw)))
    except Exception:  # noqa: BLE001
        return str(raw)


class EmailConnector(Connector):
    """Liest ungelesene Mails eines IMAP-Postfachs (nur wenn konfiguriert)."""

    name = "email"

    def sync(self) -> int:
        host = _cfg(self.config, "host", "POS_EMAIL_HOST")
        user = _cfg(self.config, "user", "POS_EMAIL_USER")
        password = _cfg(self.config, "password", "POS_EMAIL_PASSWORD")
        if not (host and user and password):
            return 0
        folder = self.config.get("folder", "INBOX")
        max_mails = int(self.config.get("max_mails", 20))
        try:
            imap = imaplib.IMAP4_SSL(host, int(self.config.get("port", 993)))
            imap.login(user, password)
            imap.select(folder)
            _, data = imap.search(None, "UNSEEN")
            ids = (data[0].split() if data and data[0] else [])[-max_mails:]
            captured = 0
            for num in ids:
                _, msg_data = imap.fetch(num, "(RFC822)")
                msg = message_from_bytes(msg_data[0][1])
                subject = _decode_subject(msg)
                sender = str(msg.get("From", ""))
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            payload = part.get_payload(decode=True)
                            if payload:
                                body = payload.decode(
                                    part.get_content_charset() or "utf-8",
                                    errors="replace",
                                )
                                break
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body = payload.decode(
                            msg.get_content_charset() or "utf-8", errors="replace"
                        )
                content = f"E-Mail von {sender}: {subject}\n\n{body[:4000]}"
                item = self.core.capture(
                    content,
                    kind="email",
                    source=f"imap://{host}/{folder}",
                    tags=["email"],
                )
                if not item.get("duplicate"):
                    captured += 1
            imap.logout()
            return captured
        except (imaplib.IMAP4.error, OSError) as exc:
            raise ConnectorError(f"IMAP-Sync fehlgeschlagen: {exc}") from exc
