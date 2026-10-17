"""
Tool registry setup.

Builds the ToolCatalog and registers every available forensic tool into it.
This is the single place where tools are added to the allow-list, so there is
one clear answer to "what tools can the agent use?" — whatever is registered here.

As we build more tools (read_usagestats, read_logcat, ...), we import them here
and register them, and nothing else in the system needs to change.
"""

from engine.tool_catalog import ToolCatalog
from tools.read_sharedprefs import READ_SHAREDPREFS
from tools.read_usagestats import READ_USAGESTATS
from tools.read_logcat import READ_LOGCAT


def build_catalog() -> ToolCatalog:
    """Create a catalog and register all available tools into it."""
    catalog = ToolCatalog()

    catalog.register(READ_SHAREDPREFS)
    catalog.register(READ_USAGESTATS)
    catalog.register(READ_LOGCAT)
    # Future tools get registered here too, e.g.:

    return catalog