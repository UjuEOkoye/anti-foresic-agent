import tempfile, os
from tools.read_logcat import _read_logcat

# Real-shape logcat lines (the "Clearing DocumentFile" traces from your findings).
SAMPLE = """05-13 16:20:01.123  1234  1234 I AndroidEraser: Starting wipe job id=7
05-13 16:20:01.200  1234  1250 D DocumentFile: Clearing DocumentFile: /storage/emulated/0/Documents/techniques_flat.xlsx
05-13 16:20:01.260  1234  1250 D DocumentFile: Clearing DocumentFile: /storage/emulated/0/Download/download.jpg
05-13 16:20:01.300  5678  5678 I ActivityManager: Displayed com.google.android.apps.nexuslauncher
05-13 16:20:02.000  1234  1234 I AndroidEraser: Wipe complete success=true
"""

tmp = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
tmp.write(SAMPLE); tmp.close()

# The AGENT supplies the pattern — here, a deletion-trace keyword.
result = _read_logcat(tmp.name, pattern="Clearing DocumentFile")

print("STATUS:", result["status"])
print("TOTAL LINES:", result["total_lines"])
print("MATCH COUNT:", result["match_count"])
for m in result["matches"]:
    print("   line", m["line"], "->", m["text"])
print("FILE PATHS:", len(result["file_paths"]))
for p in result["file_paths"]:
    print("   ", p)

# no-pattern call still extracts paths
nopat = _read_logcat(tmp.name)
print("NO-PATTERN paths:", len(nopat["file_paths"]), "| matches:", nopat["match_count"])

# missing file
missing = _read_logcat("nope_12345.txt")
print("MISSING STATUS:", missing["status"])

os.unlink(tmp.name)