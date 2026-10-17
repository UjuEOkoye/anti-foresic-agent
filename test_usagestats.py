import tempfile, os
from tools.read_usagestats import _read_usagestats

# A slice of the REAL AndroidEraser usage_stats XML (from your capture).
SAMPLE = r"""<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<usagestats version="1" endTime="4152482">
    <packages>
        <package lastTimeActive="3251728" package="com.cbinnovations.androideraser" timeActive="10315" lastEvent="1" appLaunchCount="4" />
        <package lastTimeActive="-1778720368768" package="com.android.providers.media" timeActive="0" lastEvent="0" />
    </packages>
    <event-log>
        <event time="3064608" package="com.cbinnovations.androideraser" class="com.cbinnovations.androideraser.Firstlaunch" flags="0" type="1" />
        <event time="3077731" package="com.cbinnovations.androideraser" class="com.cbinnovations.androideraser.ExtendedFileManager" flags="0" type="1" />
        <event time="3175965" package="com.cbinnovations.androideraser" flags="0" type="10" />
    </event-log>
</usagestats>"""

tmp = tempfile.NamedTemporaryFile("w", suffix="", delete=False, encoding="utf-8")
tmp.write(SAMPLE); tmp.close()

result = _read_usagestats(tmp.name)

print("STATUS:", result["status"])
print("PACKAGES:", len(result["packages"]))
for p in result["packages"]:
    print("   ", p["package"], "| launches:", p["app_launch_count"], "| timeActive:", p["time_active"])
print("EVENTS:", len(result["events"]))
for e in result["events"]:
    print("   ", e["time"], e["package"], "| class:", e["class"], "| type:", e["type"])

# also prove not_found is handled gracefully
missing = _read_usagestats("does_not_exist_12345")
print("MISSING-FILE STATUS:", missing["status"])

os.unlink(tmp.name)