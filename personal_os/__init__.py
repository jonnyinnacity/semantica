"""Personal OS - dein persoenliches KI-Operating-System.

Ein lokaler Ort, in den all dein relevantes Wissen fliesst: Capture-Inbox,
semantisches Langzeitgedaechtnis (Semantica-KG), Open Loops mit Digest,
Delegation an Agenten und Connectors fuer externe Systeme. Lokal-first,
ueber REST (127.0.0.1) und MCP (stdio) an andere Systeme anschliessbar.
"""

from .config import OSConfig
from .core import PersonalOS

__version__ = "0.1.0"

__all__ = ["PersonalOS", "OSConfig", "__version__"]
