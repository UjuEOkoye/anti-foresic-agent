"""
Test — Fixes A, B, C (after live run #4, 2026-11-17).

Run #4: verdict DETECTED / artifact_wiping / HIGH, but
  - the ACH went BLOCKED -> HIGH in one step with NO new evidence, and the
    reasons behind each judgment were not logged (Fix A);
  - it skipped the logcat overview, searched its own words, and never saw the
    58 file-clearing lines (Fix B);
  - it treated app-private data missing after uninstall as suspicious; the AW-04
    card listed that absence as an indicator (Fix C).

Proves, with NO LLM:
  A1. REPLAY OF RUN #4: blocked, then HIGH with no tool call in between -> CAPPED
      at BLOCKED; a "detected" verdict is then refused -> run ends inconclusive.
  A2. re-reading the SAME file does not count as new evidence (still capped).
  A3. after genuinely NEW evidence, the re-check may raise confidence.
  A4. "ruled_out" with no existing evidence id counts as "cannot_exclude"
      (so four evidence-free "ruled_out" give REDUCED, never HIGH).
  A5. every judgment is in the log with its reason and evidence (audit trail);
      lowering confidence is always allowed.
  B.  a logcat search WITH a pattern also returns a short overview of the
      file-referencing message kinds, before the matches; the prompt tells the
      agent to search with overview phrases and never with app names.
  C.  the AW-04 card no longer lists post-uninstall absence as an indicator, and
      the normal-uninstall card is retrieved for a post-uninstall absence query.
"""
import json, os, tempfile
from engine.llm_reasoner import LLMReasoner
from engine.bounded_loop import BoundedInvestigationLoop
from engine.tool_catalog import ToolCatalog
from engine.tool_schema import ToolSchema, FieldSpec, FieldType
from tools.read_logcat import _read_logcat
from knowledge_base import build_knowledge_base

TOOL = ToolSchema(name="read_sharedprefs", purpose="Read shared_prefs.",
                  args=[FieldSpec("artifact_path", FieldType.STRING, "p", required=True)],
                  output=[FieldSpec("entries", FieldType.OBJECT, "kv")],
                  handler=lambda artifact_path: {"status": "ok", "artifact_path": artifact_path,
                                                 "entries": {"method": "3-pass overwrite"}})
def cat():
    c = ToolCatalog(); c.register(TOOL); return c

class R:
    def __init__(self, c): self.content = c
class FakeLLM:
    def __init__(self, s): self.s = list(s)
    def invoke(self, p):
        return R(self.s.pop(0) if self.s else
                 '{"thought":"sure","action":"conclude","verdict":"detected",'
                 '"category":"artifact_wiping","evidence_ids":["E0001"],"conclusion":"high"}')

def read(path): return json.dumps({"thought": "read", "action": "call_tool",
                                   "tool_name": "read_sharedprefs", "tool_args": {"artifact_path": path}})
CLAIM = "a secure file-wiping operation was executed on this device"
def ach(disps, ev=("E0001",), quote="3-pass overwrite"):
    cats = ["normal", "another_app", "system", "acquisition"]
    return json.dumps({"thought": "check", "action": "analyze", "alt_check": {"claim": CLAIM,
        "assessments": [{"category": c, "disposition": d, "rationale": f"why {c}",
                         "evidence_ids": list(ev), "quote": quote} for c, d in zip(cats, disps)]}})
DETECT = json.dumps({"thought": "c", "action": "conclude", "verdict": "detected",
                     "category": "artifact_wiping", "evidence_ids": ["E0001"], "conclusion": "high"})
BLOCKED = ["ruled_out", "plausible", "ruled_out", "ruled_out"]
ALLOUT = ["ruled_out"] * 4

def run(script, steps=8):
    c = cat()
    return BoundedInvestigationLoop(LLMReasoner(c, llm=FakeLLM(script)), c, max_steps=steps).run()
def log(res, kind=None):
    return [e.text for e in res.memory.full_log() if kind is None or e.kind == kind]


print("A1 — replay of run #4: BLOCKED -> HIGH with no new evidence is CAPPED")
res = run([read("/p.xml"), ach(BLOCKED), ach(ALLOUT), DETECT], steps=5)
capped = [t for t in log(res, "ach") if "CAPPED" in t]
print("  ", capped[0][:110], "...")
assert capped and res.verdict == "inconclusive"
assert any("CONCLUSION REFUSED" in t for t in log(res))
print("  OK")

print("A2 — re-reading the SAME file is not new evidence")
res = run([read("/p.xml"), ach(BLOCKED), read("/p.xml"), ach(ALLOUT), DETECT], steps=6)
assert any("CAPPED" in t for t in log(res, "ach")) and res.verdict == "inconclusive"
print("  OK")

print("A3 — NEW evidence lets a re-check raise confidence")
res = run([read("/p.xml"), ach(BLOCKED), read("/q.xml"), ach(ALLOUT), DETECT])
assert not any("CAPPED" in t for t in log(res, "ach"))
assert res.verdict == "detected" and res.confidence == "high"
print("  OK  verdict:", res.verdict, "| confidence:", res.confidence)

print("A4 — 'ruled_out' without existing evidence counts as cannot_exclude")
res = run([read("/p.xml"), ach(ALLOUT, ev=()), DETECT])
assert res.verdict == "detected" and res.confidence == "reduced"          # not high
res = run([read("/p.xml"), ach(ALLOUT, ev=("E0099",)), DETECT])          # invented id
assert res.confidence == "reduced"
assert any("treated as cannot_exclude" in t for t in log(res, "ach_detail"))
print("  OK")

print("A5 — audit trail of every judgment; lowering is always allowed")
res = run([read("/p.xml"), ach(ALLOUT), ach(BLOCKED), DETECT], steps=5)
details = log(res, "ach_detail")
assert any("another_application: plausible [E0001] — why another_app" in t for t in details), details
assert res.verdict == "inconclusive"     # high -> blocked lowered immediately, detection refused
print("  OK  e.g.", details[0].strip())

print("B — pattern search also returns a short overview, before the matches")
lines = ["05-13 16:20:01.%03d  1234  1250 I System.out: Clearing DocumentFile: "
         "/storage/emulated/0/Documents/f%d.pdf" % (k, k) for k in range(30)]
lines += ["05-13 16:21:00.000  1000  1000 I ActivityManager: wipe nothing here"] * 3
f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
f.write("\n".join(lines)); f.close()
r = _read_logcat(f.name, pattern="wipe|erase")
assert r["match_count"] == 3                                   # its own words miss the 30 lines
assert r["overview_brief"]["file_path_templates"][0]["count"] == 30
assert "Clearing DocumentFile" in r["overview_brief"]["file_path_templates"][0]["template"]
keys = list(r.keys())
assert keys.index("overview_brief") < keys.index("matches")
os.unlink(f.name)
prompt = LLMReasoner(cat(), llm=object())._system_prompt()
assert "WITHOUT a pattern" in prompt and "never for an app or package name" in prompt
print("  OK")

print("C — AW-04 no longer treats post-uninstall absence as an indicator")
kb = build_knowledge_base()
aw04 = [c for c in kb.by_category("artifact_wiping") if c.card_id == "AW-04"][0]
assert any("is NOT by itself evidence" in i for i in aw04.indicators)
assert not any(i.startswith("app-private artifacts") for i in aw04.indicators)
top = [c.card_id for c in kb.retrieve("app-private shared_prefs absent after uninstall expected normal", k=3)]
print("   cards retrieved for a post-uninstall absence:", top)
assert "NB-02" in top
print("  OK")

print("\nALL FIX A/B/C TESTS PASSED")