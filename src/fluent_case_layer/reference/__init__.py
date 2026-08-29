"""Human- and agent-readable dictionary reference catalog."""

from .catalog import build_catalog, load_catalog
from .query import find_entries, get_entry

__all__ = ["build_catalog", "find_entries", "get_entry", "load_catalog"]
