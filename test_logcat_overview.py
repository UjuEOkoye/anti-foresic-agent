"""
Test — Fix 2: read_logcat gives an OVERVIEW when called without a pattern.

Live run #2 (2026-11-17): the agent called read_logcat with no pattern, got back
NO log lines (only a count + paths), and concluded "no file-operation evidence
in logcat" — although the real dump holds 58 'Clearing DocumentFile' lines.

Proves, with NO LLM, on a realistic NOISY log (44,000 lines, the file-operation
lines buried under system chatter, saved as UTF-16 like the real Windows dumps):
  1. a no-pattern call returns an overview whose file-path templates surface
     the buried file-operation lines, with the right count;
  2. the overview fits inside the agent's compact view (it is in the first
     2,500 characters the loop pins), so the agent actually SEES it;
  3. the agent can then search WITH a phrase from a template and get the exact
     lines (citable evidence);
  4. the tool stays generic: no app or tool names are hard-coded in it.
"""
import json, os, random, tempfile
from tools.read_logcat import _read_logcat
import tools.read_logcat as rl
from engine.dual_output import project
from engine.bounded_loop import BoundedInvestigationLoop

random.seed(7)
NOISE = [
    "I ActivityManager: Start proc {n}:com.android.systemui/u0a{n} for service",
    "D ConnectivityService: NetworkAgentInfo [WIFI () - {n}] validation passed",
    "W chatty  : uid={n}(system) Binder:{n}_{n} expire {n} lines",
    "I WindowManager: Changing focus from Window{{{n} u0}} to null",
    "D BatteryService: Processing new values: level={n} temperature={n}",
    "V AudioFlinger: mixer({n}) throttle end: throttle time({n})",
]
lines = []
for i in range(44000):
    pid = random.randint(100, 9999)
    lines.append(f"05-13 16:{i % 60:02d}:01.{i % 1000:03d}  {pid}  {pid} "
                 + random.choice(NOISE).format(n=random.randint(1, 99999)))
# bury 58 file-operation lines at random positions
for k in range(58):
    pos = random.randint(0, len(lines) - 1)
    lines.insert(pos, f"05-13 16:20:01.{k:03d}  1234  1250 D DocumentFile: "
                      f"Clearing DocumentFile: /storage/emulated/0/Documents/file_{k}.pdf")

tmp = tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False)
tmp.write(b"\xff\xfe" + "\r\n".join(lines).encode("utf-16-le"))   # UTF-16 like real dumps
tmp.close()

print("TEST 1 — no-pattern overview surfaces the buried file operations")
res = _read_logcat(tmp.name)
ov = res["overview"]
print("  total lines:", res["total_lines"], "| distinct templates:", ov["distinct_templates"])
print("  file_path_templates:", ov["file_path_templates"][:2])
top = ov["file_path_templates"][0]
assert "Clearing DocumentFile: <path>" in top["template"] and top["count"] == 58
assert res["match_count"] == 0 and "overview" in res
print("  OK")

print("TEST 2 — the overview is inside what the agent actually sees")
view = json.dumps(project(res), default=str)[:BoundedInvestigationLoop.MAX_VIEW_CHARS]
assert "Clearing DocumentFile" in view, "overview fell outside the agent's compact view"
print(f"  OK (found within the first {BoundedInvestigationLoop.MAX_VIEW_CHARS} chars)")

print("TEST 3 — searching WITH a phrase from the template returns the exact lines")
hit = _read_logcat(tmp.name, pattern="Clearing DocumentFile")
assert hit["match_count"] == 58 and "overview" not in hit
assert hit["matches"][0]["text"].endswith(".pdf")
print("  OK  e.g.", hit["matches"][0]["text"][-60:])

print("TEST 4 — the tool is generic (no app / tool names hard-coded)")
src = open(rl.__file__, encoding="utf-8").read().lower()
code_only = src.split('"""', 2)[2]          # skip the module docstring (history notes)
for name in ("androideraser", "cbinnovations", "shredder", "ccleaner", "file shredder"):
    assert name not in code_only, name
print("  OK")

os.unlink(tmp.name)
print("\nALL FIX-2 (LOGCAT OVERVIEW) TESTS PASSED")