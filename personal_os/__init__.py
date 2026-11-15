"""Personal OS - dein persoenliches KI-Operating-System.

Ein lokaler Ort, in den all dein relevantes Wissen fliesst: Capture-Inbox,
semantisches Langzeitgedaechtnis (Semantica-KG), Open Loops mit Digest,
Delegation an Agenten und Connectors fuer externe Systeme. Lokal-first,
ueber REST (127.0.0.1) und MCP (stdio) an andere Systeme anschliessbar.
WP1: Kontextmodell, Scopes (private/work), Provenienz, Berechtigungen.
"""

from .config import OSConfig
from .context_model import ContextModel
from .core import PersonalOS
from .permissions import PermissionManager
from .scopes import PRIVATE, WORK, redact_for_external

__version__ = "0.2.0"

__all__ = [
    "PersonalOS",
    "OSConfig",
    "ContextModel",
    "PermissionManager",
    "PRIVATE",
    "WORK",
    "redact_for_external",
    "__version__",
]
