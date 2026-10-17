"""
Tool definition structure: name, purpose, args, and output schema.

A ToolSchema fully describes one forensic tool the agent may call:
  - what it is (name, purpose)
  - what inputs it accepts and their rules (args)      -> used by the validation gate
  - what shape its result comes back in (output)       -> used by the dual-output projector
  - the function that actually runs it (handler)

Grounded in the real CleanerScope extractor output: each recovered artifact
is a JSON record with fields like package, artifact_path, raw_value,
evidence_class, mapped_label, etc. The output schema describes that shape.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class FieldType(str, Enum):
    """Allowed value types for an argument or output field."""
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    TIMESTAMP = "timestamp"
    OBJECT = "object"      # a nested structure, e.g. Wipe Files raw_value {number_passes, zero_wipe, block_size}
    LIST = "list"
    ANY = "any"            # raw_value is polymorphic (string OR object), so some fields are genuinely 'any'


@dataclass
class FieldSpec:
    """
    Describes ONE field — either an input argument or an output field.

    The validation gate checks a tool call's arguments against these specs.
    The dual-output projector uses output specs to know which fields exist.
    """
    name: str
    field_type: FieldType
    description: str
    required: bool = False
    pattern: str | None = None          # optional regex the value must match (e.g. a valid Android package)
    allowed_values: list[Any] | None = None  # optional closed set (e.g. the four evidence_class values)


@dataclass
class ToolSchema:
    """
    A complete definition of one forensic tool in the allow-listed catalog.

    IMPORTANT (novelty-protecting rule): tools are GENERIC forensic operations
    (e.g. read_sharedprefs, read_usage_stats), never named after a specific
    anti-forensic app. The agent reasons FROM what these tools return; it must
    never have a 'detect tool X' shortcut.
    """
    name: str                                  # unique identifier the agent calls, e.g. "read_sharedprefs"
    purpose: str                               # one-line description the LLM reads to decide when to use it
    args: list[FieldSpec]                      # input arguments + their validation rules
    output: list[FieldSpec]                    # the shape of the result this tool returns
    handler: Callable[..., Any] = field(repr=False)  # the function that actually performs the extraction

    def arg_names(self) -> list[str]:
        """Convenience: names of all accepted arguments."""
        return [a.name for a in self.args]

    def required_args(self) -> list[str]:
        """Convenience: names of the required arguments (used by the validation gate)."""
        return [a.name for a in self.args if a.required]