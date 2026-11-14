"""Konfiguration des Personal OS.

Local-first: alles liegt in einem Datenverzeichnis (Default ``~/.personal_os``,
ueber ``POS_HOME`` ueberschreibbar). Keine Secrets in der Datei; API-Keys
werden ausschliesslich ueber Umgebungsvariablen referenziert.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_DATA_DIR = Path.home() / ".personal_os"
ENV_DATA_DIR = "POS_HOME"
ENV_TOKEN = "POS_TOKEN"
ENV_LLM_KEY = "POS_LLM_API_KEY"


@dataclass
class ADHDConfig:
    """ADHS-freundliche Voreinstellungen fuer Digest und Erinnerungen."""

    max_items_per_section: int = 5
    stale_days: int = 7
    digest_hour: int = 8
    nudge_minutes: int = 60
    weekly_review_weekday: int = 6
    top_thing: bool = True


@dataclass
class ServerConfig:
    """Lokaler API-Server. Host ist immer Loopback-only."""

    host: str = "127.0.0.1"
    port: int = 8791
    token_env: str = ENV_TOKEN


@dataclass
class LLMConfig:
    """Optionale LLM-Anbindung fuer Delegationen (Default: deterministisch, offline)."""

    provider: str = "none"
    endpoint: str = ""
    model: str = ""
    api_key_env: str = ENV_LLM_KEY


@dataclass
class PrivacyConfig:
    """Datenschutz-Voreinstellungen (WP1): Scopes und externe Modellzugriffe."""

    external_can_see_private: bool = False
    default_capture_scope: str = "private"


@dataclass
class OSConfig:
    """Gesamtkonfiguration des Personal OS."""

    data_dir: str = ""
    profile_name: str = "Ich"
    version: int = 1
    adhd: ADHDConfig = field(default_factory=ADHDConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    memory_dim: int = 256
    connectors: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        return Path(self.data_dir) / "config.json"

    def save(self) -> None:
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @classmethod
    def resolve_data_dir(cls, data_dir: Optional[str] = None) -> str:
        if data_dir:
            return str(Path(data_dir).expanduser())
        env = os.environ.get(ENV_DATA_DIR)
        if env:
            return str(Path(env).expanduser())
        return str(DEFAULT_DATA_DIR)

    @classmethod
    def create_default(cls, data_dir: Optional[str] = None) -> "OSConfig":
        cfg = cls(data_dir=cls.resolve_data_dir(data_dir))
        cfg.save()
        return cfg

    @classmethod
    def load(cls, data_dir: Optional[str] = None) -> "OSConfig":
        resolved = cls.resolve_data_dir(data_dir)
        path = Path(resolved) / "config.json"
        if not path.exists():
            return cls.create_default(resolved)
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["data_dir"] = resolved
        cfg = cls(
            data_dir=resolved,
            profile_name=raw.get("profile_name", "Ich"),
            version=raw.get("version", 1),
            adhd=ADHDConfig(**_merge(asdict(ADHDConfig()), raw.get("adhd", {}))),
            server=ServerConfig(
                **_merge(asdict(ServerConfig()), raw.get("server", {}))
            ),
            llm=LLMConfig(**_merge(asdict(LLMConfig()), raw.get("llm", {}))),
            privacy=PrivacyConfig(
                **_merge(asdict(PrivacyConfig()), raw.get("privacy", {}))
            ),
            memory_dim=int(raw.get("memory_dim", 256)),
            connectors=raw.get("connectors", {}) or {},
        )
        return cfg


def _merge(defaults: Dict[str, Any], saved: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(defaults)
    out.update({k: v for k, v in saved.items() if k in defaults})
    return out
