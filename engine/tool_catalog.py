"""
The allow-listed registry of all forensic tools.

The catalog holds every ToolSchema the agent is permitted to call. It is an
ALLOW-LIST: the agent can only ever invoke a tool that is registered here. It
cannot invent tools or run arbitrary commands. This is a core forensic-soundness
and reproducibility guarantee — the set of possible actions is fixed and known.

The catalog is pure plumbing: register a tool, look one up, list them. It holds
no case evidence and makes no forensic decisions.
"""

from __future__ import annotations
from engine.tool_schema import ToolSchema


class ToolNotAllowed(Exception):
    """Raised when the agent references a tool name that is not in the catalog."""
    pass


class DuplicateToolName(Exception):
    """Raised when two tools are registered under the same name."""
    pass


class ToolCatalog:
    def __init__(self) -> None:
        # name -> ToolSchema. The single source of truth for what the agent may call.
        self._tools: dict[str, ToolSchema] = {}

    def register(self, tool: ToolSchema) -> None:
        """Add a tool to the allow-list. Names must be unique."""
        if tool.name in self._tools:
            raise DuplicateToolName(f"A tool named '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolSchema:
        """
        Look up a tool by name. Raises ToolNotAllowed if it isn't registered —
        this is how the validation gate rejects a hallucinated tool name before
        anything runs.
        """
        if name not in self._tools:
            raise ToolNotAllowed(f"Tool '{name}' is not in the allow-list")
        return self._tools[name]

    def is_allowed(self, name: str) -> bool:
        """True if a tool with this name is registered."""
        return name in self._tools

    def names(self) -> list[str]:
        """All registered tool names."""
        return list(self._tools.keys())

    def all_tools(self) -> list[ToolSchema]:
        """All registered ToolSchema objects (e.g. to build the agent's prompt)."""
        return list(self._tools.values())

    def describe_for_prompt(self) -> str:
        """
        A compact text listing of every tool's name + purpose, for injecting into
        the agent's system prompt so it knows what it can call. Kept concise on
        purpose — tool descriptions cost tokens (an efficiency concern, RQ4).
        """
        lines = []
        for tool in self._tools.values():
            lines.append(f"- {tool.name}: {tool.purpose}")
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._tools)