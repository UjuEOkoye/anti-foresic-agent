from tools.read_usagestats import _read_usagestats
from tools.read_logcat import _read_logcat

# --- usage_stats: the REAL capture file (Phase B) ---
u = _read_usagestats(
    r"C:\AndroidForensicsProject\CleanerScope\captures\AndriodEraser\AndroidEraser2\PhaseB_PostClean_LogicalRun\usage_stats\0\daily\1778720368768"
)
print("USAGESTATS:", u["status"], "| packages:", len(u["packages"]), "| events:", len(u["events"]))
for p in u["packages"]:
    if p["app_launch_count"]:          # show only apps that were actually launched
        print("   ", p["package"], "| launches:", p["app_launch_count"], "| timeActive:", p["time_active"])

# --- logcat: the REAL full dump (Phase B) ---
lg = _read_logcat(
    r"C:\AndroidForensicsProject\CleanerScope\captures\AndriodEraser\AndroidEraser2\PhaseB_PostClean_Logcat\01_logcat_full_dump_afterwipe.txt",
    pattern="Clearing DocumentFile",
)
print("LOGCAT:", lg["status"], "| lines:", lg["total_lines"],
      "| matches:", lg["match_count"], "| paths:", len(lg["file_paths"]))
for p in lg["file_paths"][:8]:         # first few real paths found
    print("   ", p)