"""
Validation gate: check a tool call against its schema BEFORE it runs.

When the agent proposes "call tool X with these arguments", the gate verifies:
  1. tool X is in the allow-listed catalog (not a hallucinated name),
  2. all required arguments are present,
  3. each provided argument obeys its FieldSpec rules (type / pattern / allowed set).

If every check passes, the call is valid and may execute.
If any check fails, the call is REJECTED with a structured error and the tool
NEVER runs — the agent receives the error and can correct its next attempt.

Principle (decoupled execution): the agent's *rationale* for wanting a tool does
not authorize execution — only passing this gate does.
"""

from __future__ import annotations
import re
from dataclasses import dataclass

from engine.tool_catalog import ToolCatalog, ToolNotAllowed
from engine.tool_schema import FieldSpec, FieldType


@dataclass
class ValidationResult:
    """The outcome of checking one tool call."""
    valid: bool
    tool_name: str
    errors: list[str]        # human-readable reasons the call was rejected (empty if valid)

    def as_observation(self) -> dict:
        """
        A structured result the agent can read back. On failure this becomes the
        'observation' fed into the agent's next reasoning step so it can self-correct.
        """
        if self.valid:
            return {"status": "valid", "tool": self.tool_name, "errors": []}
        return {"status": "invalid", "tool": self.tool_name, "errors": self.errors}


def _check_type(value, field_type: FieldType) -> bool:
    """Is `value` consistent with the declared FieldType? ANY always passes."""
    if field_type == FieldType.ANY:
        return True
    if field_type == FieldType.STRING:
        return isinstance(value, str)
    if field_type == FieldType.INTEGER:
        # bool is a subclass of int in Python, so exclude it explicitly
        return isinstance(value, int) and not isinstance(value, bool)
    if field_type == FieldType.BOOLEAN:
        return isinstance(value, bool)
    if field_type == FieldType.OBJECT:
        return isinstance(value, dict)
    if field_type == FieldType.LIST:
        return isinstance(value, list)
    if field_type == FieldType.TIMESTAMP:
        # accept a string for now; stricter timestamp parsing can come later
        return isinstance(value, str)
    return True


def _check_one_arg(spec: FieldSpec, value) -> list[str]:
    """Check a single provided argument against its FieldSpec. Returns error strings."""
    errors: list[str] = []

    # type
    if not _check_type(value, spec.field_type):
        errors.append(
            f"argument '{spec.name}' must be of type {spec.field_type.value}, "
            f"got {type(value).__name__}"
        )

    # pattern (only meaningful for strings)
    if spec.pattern is not None and isinstance(value, str):
        if re.fullmatch(spec.pattern, value) is None:
            errors.append(f"argument '{spec.name}' does not match required pattern")

    # allowed values (closed set)
    if spec.allowed_values is not None and value not in spec.allowed_values:
        errors.append(
            f"argument '{spec.name}' must be one of {spec.allowed_values}, got '{value}'"
        )

    return errors


def validate_call(catalog: ToolCatalog, tool_name: str, args: dict) -> ValidationResult:
    """
    Validate a proposed tool call against the catalog + the tool's schema.

    catalog   : the allow-listed ToolCatalog
    tool_name : the tool the agent wants to call
    args      : the arguments the agent provided, as a dict {name: value}
    """
    errors: list[str] = []

    # 1. Is the tool on the allow-list?
    try:
        tool = catalog.get(tool_name)
    except ToolNotAllowed as exc:
        return ValidationResult(valid=False, tool_name=tool_name, errors=[str(exc)])

    # 2. Are all required arguments present?
    for req in tool.required_args():
        if req not in args:
            errors.append(f"missing required argument '{req}'")

    # 3. Check each provided argument against its spec.
    spec_by_name = {spec.name: spec for spec in tool.args}
    for name, value in args.items():
        if name not in spec_by_name:
            errors.append(f"unknown argument '{name}' (not accepted by {tool_name})")
            continue
        errors.extend(_check_one_arg(spec_by_name[name], value))

    return ValidationResult(valid=(len(errors) == 0), tool_name=tool_name, errors=errors)