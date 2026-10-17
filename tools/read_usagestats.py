"""
tools/read_usagestats.py

A box-6.5 forensic tool: read an Android usage_stats XML file.

usage_stats is the app-use TIMELINE Android keeps per time-bucket
(usage_stats/<user>/daily|weekly|monthly|yearly/<epoch>). It is one of the most
durable artifacts — it can survive app uninstall AND device reboot — so it is
central to the concealment / phase-survival story (RQ2).

This tool extracts two things, VERBATIM, and interprets nothing:
  1. per-package usage counters (package, lastTimeActive, timeActive, lastEvent,
     appLaunchCount)
  2. the ordered event/activity timeline (time, package, class, type)

It is GENERIC: it knows nothing about any specific app. Deciding what a class
name or an event `type` number MEANS is the agent/KB's job, never the tool's.
"not_found" is a first-class result (an acquisition limit, NOT proof of a clean
device).
"""

import os
import xml.etree.ElementTree as ET

from engine.tool_schema import FieldType, FieldSpec, ToolSchema


def _to_int(value):
    """Convert a numeric XML attribute to int; fall back to the raw value."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return value


def _read_usagestats(artifact_path):
    """Parse one usage_stats XML file. Returns a dict; never raises on bad input."""
    if not os.path.exists(artifact_path):
        return {
            "status": "not_found",
            "artifact_path": artifact_path,
            "packages": [],
            "events": [],
            "note": ("usage_stats file not found at this path — an acquisition "
                     "limit, NOT proof of a clean device."),
        }

    try:
        root = ET.parse(artifact_path).getroot()
    except Exception as exc:  # malformed / truncated XML
        return {
            "status": "unreadable",
            "artifact_path": artifact_path,
            "packages": [],
            "events": [],
            "note": f"could not parse usage_stats XML: {exc}",
        }

    # 1. per-package usage counters (appLaunchCount is absent on idle packages)
    packages = []
    for pkg in root.findall("packages/package"):
        packages.append({
            "package": pkg.get("package"),
            "last_time_active": _to_int(pkg.get("lastTimeActive")),
            "time_active": _to_int(pkg.get("timeActive")),
            "last_event": _to_int(pkg.get("lastEvent")),
            "app_launch_count": _to_int(pkg.get("appLaunchCount")),  # may be None
        })

    # 2. the activity/event timeline, order preserved as written in the file
    #    (class is absent on some event types, e.g. type 10 / 12)
    events = []
    for ev in root.findall("event-log/event"):
        events.append({
            "time": _to_int(ev.get("time")),
            "package": ev.get("package"),
            "class": ev.get("class"),   # may be None
            "type": _to_int(ev.get("type")),
        })

    return {
        "status": "ok",
        "artifact_path": artifact_path,
        "version": root.get("version"),
        "end_time": _to_int(root.get("endTime")),
        "packages": packages,
        "events": events,
        "note": f"parsed {len(packages)} package record(s) and {len(events)} event(s).",
    }


READ_USAGESTATS = ToolSchema(
    name="read_usagestats",
    purpose=(
        "Read an Android usage_stats XML file (an app-use timeline). Returns, per "
        "package, its usage counters, plus the ordered event/activity sequence "
        "(package, class, event-type, timestamp). Extracts facts only; does not "
        "interpret them or know anything about any specific app."
    ),
    args=[
        FieldSpec(
            name="artifact_path",
            field_type=FieldType.STRING,
            description="Path to a usage_stats XML file (e.g. usage_stats/0/daily/<epoch>).",
            required=True,
        ),
    ],
    output=[
        FieldSpec(name="status", field_type=FieldType.STRING,
                  description="ok | not_found | unreadable"),
        FieldSpec(name="packages", field_type=FieldType.LIST,
                  description="per-package usage counters"),
        FieldSpec(name="events", field_type=FieldType.LIST,
                  description="ordered activity/event timeline"),
    ],
    handler=_read_usagestats,
)