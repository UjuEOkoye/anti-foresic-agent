"""
tools/read_recent_tasks.py — box 6.5 tool (added 2026-11-19, final AW fix).

Reads an Android recent-task record (a system file such as
/data/system_ce/0/recent_tasks/<id>_task.xml). The operating system writes one
of these for each task in the "recents" list. Per the CleanerScope findings, a
task record survives an app's uninstall and is cleared by a reboot, so it is a
supporting system-level trace that an app was opened.

GENERIC: it returns the record's fields exactly as stored (e.g. which activity
started the task, the calling package, the uid, the last time it was moved).
It knows nothing about any app and does not interpret the fields.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET

from engine.tool_schema import ToolSchema, FieldSpec, FieldType

_MAX_CHILDREN = 20


def _read_recent_tasks(artifact_path: str) -> dict:
    if not os.path.isfile(artifact_path):
        return {"status": "not_found", "artifact_path": artifact_path, "task": {}, "children": [],
                "note": "file not present in this acquisition (an acquisition limit, NOT 'clean')"}
    try:
        root = ET.parse(artifact_path).getroot()
    except (ET.ParseError, OSError) as exc:
        return {"status": "unreadable", "artifact_path": artifact_path, "task": {}, "children": [],
                "note": f"could not parse: {exc}"}
    children = [{"tag": c.tag, "attributes": dict(c.attrib)} for c in list(root)[:_MAX_CHILDREN]]
    return {
        "status": "ok",
        "artifact_path": artifact_path,
        "root_tag": root.tag,
        "task": dict(root.attrib),          # every attribute exactly as stored
        "children": children,
        "note": f"{len(root.attrib)} task attribute(s), {len(list(root))} child element(s)",
    }


READ_RECENT_TASKS = ToolSchema(
    name="read_recent_tasks",
    purpose=(
        "Read an Android recent-task record (system file, e.g. .../recent_tasks/<id>_task.xml). "
        "Returns the task's stored fields exactly (e.g. the activity that started it, the "
        "calling package, the uid, last time moved). Generic: no interpretation."
    ),
    args=[FieldSpec(name="artifact_path", field_type=FieldType.STRING,
                    description="path to the recent-task XML file", required=True)],
    output=[
        FieldSpec(name="task", field_type=FieldType.OBJECT, description="the task's attributes"),
        FieldSpec(name="children", field_type=FieldType.LIST, description="child elements"),
    ],
    handler=_read_recent_tasks,
)