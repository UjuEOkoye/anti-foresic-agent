"""
engine/evidence_digest.py — BOX 5: EVIDENCE DISTILLATION (built 2026-11-19).

Why this exists
---------------
Across every live run the agent reached wrong or weak conclusions for ONE
recurring reason: it investigated through a keyhole — one artifact per step,
each seen only as a short, cut-down view, guessing what to search next. The
decisive proof in a capture is usually a CROSS-ARTIFACT JOIN (the same files
named in an app's own report and in the system log, written by that app's
process, inside the same time window). Fragment-by-fragment reading makes such
joins unreliable for a language model.

The v6 pipeline already specifies the remedy (box 5): "inspect sources, create
compact structured representations, preserve timestamps/ids/relationships,
flag faint signals, preserve access to the complete evidence."

What it does
------------
Before the agent starts, deterministic code:
  1. reads EVERY primary artifact IN FULL with the same allow-listed tools the
     agent uses (each read is preserved in the audit store with an evidence id
     and hash, exactly like an agent tool call);
  2. extracts generic facts per artifact TYPE (no app names, no app rules);
  3. computes generic cross-artifact links:
       - file names that appear in more than one artifact,
       - which process wrote the system-log lines about files, and which app
         that process belongs to (via the system's own "Start proc" line),
       - which apps appear in which artifacts,
       - the time windows of each source (normalised to one format);
  4. hands the agent a compact CASE DIGEST of these facts, each with the
     evidence id it comes from and an exact quote it can cite.

The agent then REASONS and JUDGES (hypotheses, alternative explanations,
verdict) over complete facts. Mechanism/cognition split: code reads and
computes; the model interprets. The digest can be switched off for ablation
(RQ4: with vs without distillation).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.read_logcat import _decode_log_bytes, _split_tag, _template, _PATH_RE, _TEMPLATE_PATH_RE

# A file name: something with a short extension containing a letter (".jpeg", ".pdf").
_FILE_NAME_RE = re.compile(r"[^/\\\"'<>|:]{1,200}\.(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{1,5}$")
# Standard logcat line start: "MM-DD HH:MM:SS.mmm  PID  TID L"
_LOG_HEAD_RE = re.compile(r"(\d\d-\d\d \d\d:\d\d:\d\d)\.\d+\s+(\d+)\s+(\d+)\s+[VDIWEF]\s")
# The system's own process-start record: "Start proc <pid>:<package>/<uid> ..."
_START_PROC_RE = re.compile(r"Start proc (\d+):([A-Za-z0-9_.]+)/(\S+)")
# Android package-like token
_PKG_RE = re.compile(r"\b[a-z][a-z0-9_]*(?:\.[a-z0-9_]+){2,}\b")

_MAX_LIST = 6          # examples shown per list in the digest text


def _norm_time(text: str) -> str | None:
    """Normalise common timestamp shapes to 'MM-DD HH:MM:SS' for comparison."""
    t = str(text).strip()
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(t, fmt).strftime("%m-%d %H:%M:%S")
        except ValueError:
            pass
    if re.fullmatch(r"\d\d-\d\d \d\d:\d\d:\d\d", t):
        return t
    return None


def _walk(value: Any, path: str = ""):
    """Yield (field_path, scalar) for every scalar inside nested dicts/lists."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v, f"{path}[]")
    else:
        yield path, value


@dataclass
class Digest:
    text: str                                   # what the agent is shown
    read_paths: set[str] = field(default_factory=set)
    evidence: list[tuple[str, str]] = field(default_factory=list)   # (evidence_id, header)
    facts: dict = field(default_factory=dict)   # structured facts (for tests / reports)


def build_digest(inventory: list[dict], catalog, dual) -> Digest:
    """
    Read every primary artifact in full, extract facts, compute cross-artifact
    links. `inventory` is main.scan_capture() output (excluded items skipped).
    Every read goes through the allow-listed tool and the audit store.
    """
    def call(tool: str, **args) -> tuple[str, dict]:
        raw = catalog.get(tool).handler(**args)
        bundle = dual.handle(tool, raw, keep_fields=None)
        return bundle["evidence"]["evidence_id"], raw

    items = [i for i in inventory if not i.get("excluded")]
    lines: list[str] = []
    ev_list: list[tuple[str, str]] = []
    read: set[str] = set()
    facts: dict = {"prefs": [], "usage": [], "tasks": [], "logcat": [], "links": {}}

    app_presence: dict[str, set[str]] = defaultdict(set)      # package -> artifact kinds
    file_names: dict[str, dict[str, str]] = defaultdict(dict)  # name -> {kind: evidence_id}

    # ---- app-private stores (shared_prefs) ------------------------------------
    for it in [i for i in items if i["type"] == "shared_prefs"]:
        eid, raw = call("read_sharedprefs", artifact_path=it["path"])
        read.add(it["path"]); ev_list.append((eid, f"shared_prefs {it['path']}"))
        pth = Path(it["path"])
        for part in list(pth.parent.parts) + [pth.stem]:
            if _PKG_RE.fullmatch(part):
                app_presence[part].add(f"app-private store [{eid}]")
        for key, records in (raw.get("decoded_json") or {}).items():
            scalars: dict[str, Counter] = defaultdict(Counter)
            list_totals: Counter = Counter()
            times: list[str] = []
            for rec in records:
                for fpath, val in _walk(rec):
                    leaf = fpath.split(".")[-1]
                    if isinstance(val, str) and _norm_time(val):
                        times.append(_norm_time(val))
                    elif isinstance(val, str) and _FILE_NAME_RE.fullmatch(val.strip()):
                        file_names[val.strip()]["app-private record"] = eid
                    elif isinstance(val, (bool, int, float, str)) and "[]" not in fpath \
                            and not leaf.lower().endswith("id") and len(str(val)) <= 40:
                        scalars[fpath][val] += 1
                if isinstance(rec, dict):
                    for k, v in rec.items():
                        if isinstance(v, list):
                            list_totals[k] += len(v)
            n = len(records)
            uniform = [f"{k}={next(iter(c))!r} ({c.most_common(1)[0][1]}/{n})"
                       for k, c in sorted(scalars.items()) if len(c) == 1]
            facts["prefs"].append({"evidence_id": eid, "key": key, "records": n,
                                   "uniform_fields": uniform, "list_totals": dict(list_totals),
                                   "time_range": (min(times), max(times)) if times else None})
            lines.append(f"- [{eid}] app-private store {Path(it['path']).name}: key '{key}' holds "
                         f"{n} structured record(s).")
            if uniform:
                lines.append(f"    same in every record: {', '.join(uniform[:12])}")
            if list_totals:
                lines.append("    list sizes summed over records: "
                             + ", ".join(f"{k}={v}" for k, v in list_totals.items()))
            if times:
                lines.append(f"    record times span {min(times)} -> {max(times)} (normalised)")

    # ---- usage timeline -------------------------------------------------------
    for it in [i for i in items if i["type"] == "usage_stats"]:
        eid, raw = call("read_usagestats", artifact_path=it["path"])
        read.add(it["path"]); ev_list.append((eid, f"usage_stats {it['path']}"))
        launched = [p for p in raw.get("packages", []) if (p.get("app_launch_count") or 0) > 0]
        acts: dict[str, list[str]] = defaultdict(list)
        for e in raw.get("events", []):
            cls = e.get("class")
            if cls and cls not in acts[e.get("package")]:
                acts[e.get("package")].append(cls)
        sig = [(p["package"], p.get("app_launch_count"), p.get("time_active")) for p in launched]
        facts["usage"].append({"evidence_id": eid, "path": it["path"], "launched": sig})
        for p in launched:
            app_presence[p["package"]].add(f"usage timeline [{eid}]")
        same = next((u for u in facts["usage"][:-1] if u["launched"] == sig), None)
        if same:
            lines.append(f"- [{eid}] usage timeline {it['path'].split('/usage')[0].split('/')[-1]}: "
                         f"IDENTICAL launch counts/active times to [{same['evidence_id']}]")
            continue
        lines.append(f"- [{eid}] usage timeline {it['path'].split('/usage')[0].split('/')[-1]}: "
                     f"{len(raw.get('packages', []))} packages, {len(launched)} with launches: "
                     + "; ".join(f"{p['package']} launches={p.get('app_launch_count')} "
                                 f"time_active={p.get('time_active')}" for p in launched[:_MAX_LIST]))
        for p in launched:
            if acts.get(p["package"]):
                lines.append(f"    activities of {p['package']}: " + " -> ".join(acts[p['package']][:_MAX_LIST]))

    # ---- recent tasks ---------------------------------------------------------
    for it in [i for i in items if i["type"] == "recent_tasks"]:
        eid, raw = call("read_recent_tasks", artifact_path=it["path"])
        read.add(it["path"]); ev_list.append((eid, f"recent_tasks {it['path']}"))
        t = raw.get("task", {})
        facts["tasks"].append({"evidence_id": eid, "path": it["path"], "task": t})
        keep = {k: t[k] for k in ("real_activity", "calling_package", "affinity", "effective_uid",
                                  "last_time_moved") if k in t}
        lines.append(f"- [{eid}] recent task {it['path'].split('/recent_tasks')[0].split('/')[-1]}: "
                     + ", ".join(f'{k}="{v}"' for k, v in keep.items()))
        for v in keep.values():
            for pkg in _PKG_RE.findall(str(v)):
                app_presence[pkg].add(f"recent task [{eid}]")

    # ---- system log -----------------------------------------------------------
    for it in [i for i in items if i["type"] == "logcat"]:
        eid, raw = call("read_logcat", artifact_path=it["path"])          # overview read
        read.add(it["path"]); ev_list.append((eid, f"logcat overview {it['path']}"))
        try:
            text = _decode_log_bytes(Path(it["path"]).read_bytes())
        except OSError:
            continue
        pid_owner: dict[str, tuple[str, str]] = {}
        file_groups: dict[tuple, dict] = {}
        for ln in text.splitlines():
            m = _START_PROC_RE.search(ln)
            if m:
                pid_owner[m.group(1)] = (m.group(2), m.group(3))
            if not _PATH_RE.search(ln):
                continue
            h = _LOG_HEAD_RE.search(ln)
            if not h:
                continue
            tag, msg = _split_tag(ln)
            key = (h.group(2), _template(tag, msg))
            g = file_groups.setdefault(key, {"count": 0, "first": h.group(1), "last": h.group(1),
                                             "names": [], "example": ln.strip()})
            g["count"] += 1
            g["last"] = h.group(1)
            for pm in list(_TEMPLATE_PATH_RE.finditer(msg)) or list(_PATH_RE.finditer(msg)):
                g["names"].append(pm.group(0).rstrip("/").split("/")[-1])
        # groups by (pid, message kind); keep those not explained as routine chatter:
        # ranked by count, and only groups whose PID belongs to a known started app.
        ranked = sorted(file_groups.items(), key=lambda kv: -kv[1]["count"])
        shown = 0
        for (pid, tmpl), g in ranked:
            owner = pid_owner.get(pid)
            if owner is None or shown >= 3:
                continue
            shown += 1
            # evidence: the exact lines, and the exact process-start line
            phrase = re.escape(tmpl.split(": ", 1)[-1].split("<")[0].strip())
            lid, lraw = call("read_logcat", artifact_path=it["path"], pattern=phrase)
            sid, sraw = call("read_logcat", artifact_path=it["path"], pattern=f"Start proc {pid}:")
            ev_list += [(lid, f"logcat lines '{tmpl}'"), (sid, f"logcat Start proc {pid}")]
            start_line = (sraw.get("matches") or [{}])[0].get("text", "")
            for n in g["names"]:
                file_names[n]["system log (pid %s)" % pid] = lid
            app_presence[owner[0]].add(f"system log process {pid} [{sid}]")
            facts["logcat"].append({"evidence_id": lid, "start_evidence_id": sid, "pid": pid,
                                    "owner": owner[0], "template": tmpl, "count": g["count"],
                                    "window": (g["first"], g["last"])})
            lines.append(f"- [{lid}] system log: {g['count']} line(s) '{tmpl}' written by PID {pid}, "
                         f"{g['first']} -> {g['last']}.")
            lines.append(f"    [{sid}] PID {pid} belongs to {owner[0]} per the system's own line: "
                         f"\"{start_line[:160]}\"")
            lines.append(f"    example line: \"{g['example'][:180]}\"")
        if not shown:
            lines.append(f"- [{eid}] system log: no file-referencing lines from an identifiable app process.")

    # ---- cross-artifact links -------------------------------------------------
    link_lines: list[str] = []
    multi = {n: kinds for n, kinds in file_names.items() if len(kinds) >= 2}
    by_pair: dict[tuple, list[str]] = defaultdict(list)
    for n, kinds in multi.items():
        by_pair[tuple(sorted(kinds))].append(n)
    for pair, names in sorted(by_pair.items(), key=lambda kv: -len(kv[1])):
        refs = ", ".join(f"{k} [{file_names[names[0]][k]}]" for k in pair)
        totals = {k: sum(1 for n in file_names if k in file_names[n]) for k in pair}
        link_lines.append(f"- {len(names)} file name(s) appear in BOTH {refs} "
                          f"(totals per source: " + ", ".join(f"{k}={v}" for k, v in totals.items())
                          + f"); e.g. " + "; ".join(f'"{n}"' for n in sorted(names)[:4]))
    facts["links"]["shared_file_names"] = {" + ".join(k): v for k, v in by_pair.items()}
    for pkg, where in sorted(app_presence.items(), key=lambda kv: -len(kv[1])):
        kinds = {w.split(" [")[0].split(" process")[0] for w in where}
        if len(kinds) >= 2:
            link_lines.append(f"- app {pkg} appears in {len(kinds)} different artifact kinds "
                              f"({len(where)} records): " + "; ".join(sorted(where)))
    facts["links"]["app_presence"] = {k: sorted(v) for k, v in app_presence.items()}
    windows = [f"app-private records {p['time_range'][0]} -> {p['time_range'][1]} [{p['evidence_id']}]"
               for p in facts["prefs"] if p["time_range"]]
    windows += [f"system-log lines by PID {l['pid']} {l['window'][0]} -> {l['window'][1]} [{l['evidence_id']}]"
                for l in facts["logcat"]]
    if len(windows) >= 2:
        link_lines.append("- time windows (same normalised format): " + " | ".join(windows))

    header = (f"=== CASE DIGEST (box 5: deterministic pre-pass; EVERY artifact read IN FULL; "
              f"{len(read)} artifacts, {len(ev_list)} evidence records) ===\n"
              "These are FACTS computed by code from the complete evidence (not guesses). Cite the "
              "evidence ids shown; quoted text is exact. Use search_evidence for any detail.\n")
    body = "PER ARTIFACT:\n" + "\n".join(lines) + "\nCROSS-ARTIFACT LINKS (computed):\n" \
        + ("\n".join(link_lines) if link_lines else "- none found")
    # The digest is itself preserved as evidence (derived, deterministic, every line
    # pointing at its source ids), so the agent can quote a digest line and cite it.
    did = dual.handle("box5_digest", {"digest": body, "facts": facts,
                                      "sources": [e for e, _ in ev_list]})["evidence"]["evidence_id"]
    ev_list.append((did, "box-5 case digest (derived from the evidence above)"))
    text = (header + f"The digest itself is evidence [{did}]: to quote a digest line, cite [{did}] "
            "(or quote the original text and cite its source id).\n" + body)
    return Digest(text=text, read_paths=read, evidence=ev_list, facts=facts)