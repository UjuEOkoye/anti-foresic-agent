"""
knowledge_base/cards.py — THE CONTENT (your research artifact; edit/expand this).

Organised by YOUR SoK taxonomy (SoK: Anti-Forensics Evolution, Platform Coverage,
and Mobile Residual Evidence). Six top-level categories exist:

  AW  — Artifact Wiping              (file wiping, secure deletion, sanitization)
  TO  — Trail Obfuscation           (log/timestamp tampering, data fabrication, framing)
  DH  — Data Hiding                 (steganography, ENCRYPTION, data obscurity, deniable enc.)
  PIA — Presence/Installation       (presence of anti-forensic tools / files / install remnants)
  AT  — Attacks on Tools            (attacking the forensic software itself)   << OUT OF SCOPE
  AAF — AI / Adversarial AF         (GAN/deepfake, mostly image/video domain)  << OUT OF SCOPE

SCOPE for THIS detector (it reasons from on-device artifacts): AW, TO, DH, PIA.
  - AT = our Adversary-B (attacks on the examiner's tools), scoped as future work.
  - AAF = multimedia/image domain, not mobile on-device artifacts.
These two are documented here for completeness but have NO detection cards.

GOLDEN RULE: cards describe BEHAVIOUR CLASSES + artifact TYPES, never APP NAMES.
(Artifact types like shared_prefs / usage_stats / logcat are fine; app names are not.
test_knowledge_base.py enforces the no-app-name rule.)

The AW cards below are grounded in the CleanerScope empirical findings, generalised
to the behaviour/artifact-type level so they still catch UNSEEN wiping tools.
"""
from knowledge_base.kb import KnowledgeCard


STARTER_CARDS: list[KnowledgeCard] = [

    # ======================= AW — ARTIFACT WIPING =========================
    KnowledgeCard(
        card_id="AW-01",
        title="Method-recorded secure overwriting",
        category="artifact_wiping",
        summary=(
            "A secure-deletion action that overwrites a file's bytes (often multiple "
            "passes) so content cannot be recovered. Such tools frequently leave a "
            "configuration or report artifact that records HOW the wipe was done."
        ),
        indicators=[
            "a shared_prefs or config report entry recording a wipe method or standard",
            "a recorded pass count and/or overwrite pattern (multi-pass overwriting)",
            "recorded start/end timestamps and total bytes processed for a wipe run",
            "a per-file outcome list (which files, success/failure) inside one report value",
        ],
        keywords=["wipe", "wiping", "wiped", "overwrite", "overwritten", "overwriting",
                  "secure", "delete", "deletion", "erase", "passes", "pass", "method",
                  "pattern", "report", "sanitize", "scrub", "unrecoverable", "bytes"],
    ),
    KnowledgeCard(
        card_id="AW-02",
        title="Wiping behavioural workflow (select-then-operate)",
        category="artifact_wiping",
        summary=(
            "Wiping tools show a recognisable usage pattern: the app is launched, enters a "
            "file-chooser / file-manager style workflow, then performs rapid file operations "
            "over many targets in a short window."
        ),
        indicators=[
            "a usage timeline showing an app launch followed by a file-selection activity",
            "a burst of file operations concentrated in a short time window",
            "an app foreground session immediately before many files change or disappear",
            "repeated launches of the same app around file-deletion activity",
        ],
        keywords=["usage", "timeline", "workflow", "launch", "foreground", "file", "manager",
                  "selection", "chooser", "activity", "burst", "sequence", "behaviour"],
    ),
    KnowledgeCard(
        card_id="AW-03",
        title="Cross-artifact corroboration of wiping",
        category="artifact_wiping",
        summary=(
            "A wipe is far better supported when the SAME targeted filenames appear in two "
            "independent artifacts — e.g. path traces in a log AND a per-file report in a "
            "config artifact — than when it appears in only one."
        ),
        indicators=[
            "the same file paths referenced in both a log and a config/report artifact",
            "log lines referencing clearing or deleting specific file paths",
            "agreement between a timeline, a log, and a config report on the same event",
        ],
        keywords=["corroborate", "corroboration", "logcat", "log", "paths", "clearing",
                  "independent", "agreement", "cross", "both", "sources", "filenames"],
    ),
    KnowledgeCard(
        card_id="AW-04",
        title="Artifact survival vs destruction (durable timeline, destroyed app-private data)",
        category="artifact_wiping",
        summary=(
            "On mobile, some artifacts survive even uninstall and reboot (an app-usage "
            "timeline), while an app's own private data (its config store, recent-task and "
            "snapshot entries) is destroyed by uninstall or reboot. So a wiping app's RUN can "
            "still be proven from durable artifacts after the app and its private data are gone."
        ),
        indicators=[
            "a durable usage timeline still showing an app ran, after the app was removed",
            "app-private artifacts (config store, recent tasks, snapshots) absent after uninstall/reboot",
            "proof of a run surviving in one artifact while the richer detail is gone from another",
        ],
        keywords=["survive", "survival", "durable", "persist", "uninstall", "reboot",
                  "usagestats", "usage", "recent", "tasks", "snapshots", "destroyed",
                  "absent", "missing", "gone", "private", "data"],
    ),

    # ======================= TO — TRAIL OBFUSCATION =======================
    KnowledgeCard(
        card_id="TO-01",
        title="Trail obfuscation (logs, timestamps, histories)",
        category="trail_obfuscation",
        summary=(
            "Attacking the RECORD of what happened rather than the data itself — clearing or "
            "truncating logs, altering or back-dating timestamps, wiping histories, or "
            "fabricating records to mislead a timeline."
        ),
        indicators=[
            "gaps, resets, or sudden truncation in an otherwise continuous timeline",
            "timestamps inconsistent across artifacts that should agree (possible timestomping)",
            "histories or recent-item lists cleared or unexpectedly empty",
            "records that contradict other evidence (possible fabrication/misdirection)",
        ],
        keywords=["obfuscate", "obfuscation", "timestamp", "timestomp", "log", "logs",
                  "history", "clear", "truncate", "timeline", "tamper", "fabricate",
                  "fabrication", "misdirection", "framing", "gap", "backdate"],
    ),

    # ======================= DH — DATA HIDING =============================
    KnowledgeCard(
        card_id="DH-01",
        title="Data hiding (concealment; includes encryption & steganography)",
        category="data_hiding",
        summary=(
            "Keeping data present but hard to find or read. Sub-types include ENCRYPTION "
            "(making content unreadable without a key), steganography (embedding data inside "
            "other files), data obscurity (renaming/relocating/disguising), and deniable "
            "encryption. Encryption is legitimate in general, so it is anti-forensic only in "
            "context."
        ),
        indicators=[
            "high-entropy blobs or an encrypted container/keystore where readable data is expected",
            "files whose extension does not match their actual content (disguise)",
            "user content stored in unexpected or system-looking locations",
            "an app presenting a harmless face but holding a private, locked store (vault)",
            "hidden directories or files excluded from normal listings",
        ],
        keywords=["hide", "hiding", "conceal", "encrypt", "encryption", "cipher", "key",
                  "keystore", "entropy", "steganography", "stego", "vault", "disguise",
                  "rename", "relocate", "hidden", "container", "deniable", "obscurity"],
    ),

    # ======================= PIA — PRESENCE / INSTALLATION ================
    KnowledgeCard(
        card_id="PIA-01",
        title="Presence or installation traces of an anti-forensic utility",
        category="presence_installation",
        summary=(
            "The mere presence of a tool whose PURPOSE is anti-forensic — or leftovers of its "
            "installation/removal — is itself an indicator. Judged by GENERIC profile, never by "
            "a list of known app names, so it still flags unfamiliar tools."
        ),
        indicators=[
            "an installed or recently-removed package whose declared function is bulk/secure deletion",
            "an app requesting unusually broad file-access or management permissions",
            "installation or configuration remnants of a deletion/cleaning utility",
            "a package present during the activity window and removed shortly afterward",
        ],
        keywords=["presence", "installed", "install", "package", "apk", "permission",
                  "remnant", "leftover", "uninstalled", "utility", "cleaner", "tool"],
    ),

    # ======================= NORMAL BASELINES (feeds ACH 6.7) =============
    KnowledgeCard(
        card_id="NB-01",
        title="Normal: routine deletion and cache clearing",
        category="normal_baseline",
        summary=(
            "Devices delete things constantly for innocent reasons. Ordinary deletion usually "
            "leaves a recoverable trace (a tombstone, a trash entry, an unlinked-but-not-"
            "overwritten file) rather than overwriting the bytes."
        ),
        indicators=[
            "operating-system trash or tombstone entries for removed files",
            "cache directories emptied as part of normal maintenance",
            "a media or file app removing user-chosen files during ordinary use",
            "a single delete with no overwrite pattern and no multi-pass method recorded",
        ],
        keywords=["normal", "routine", "cache", "trash", "tombstone", "delete",
                  "cleanup", "maintenance", "recycle", "benign", "ordinary"],
    ),
    KnowledgeCard(
        card_id="NB-02",
        title="Normal: app uninstall removes the app's own data",
        category="normal_baseline",
        summary=(
            "When any app is uninstalled, the system removes that app's private data by design. "
            "So app-private artifacts being absent after an uninstall is EXPECTED, and is not by "
            "itself evidence of anti-forensic wiping."
        ),
        indicators=[
            "an app's private config/data gone because the app was uninstalled",
            "recent-task or snapshot entries cleared by a normal reboot",
            "absence that lines up exactly with a normal uninstall or reboot event",
        ],
        keywords=["uninstall", "removed", "normal", "reboot", "private", "expected",
                  "absent", "cleared", "benign"],
    ),
    KnowledgeCard(
        card_id="NB-03",
        title="Normal: built-in privacy features",
        category="normal_baseline",
        summary=(
            "Many mainstream apps include privacy features that reduce stored traces by design. "
            "Their presence is not by itself evidence of anti-forensic intent."
        ),
        indicators=[
            "a browser private/incognito mode leaving little history",
            "a messaging feature that expires or removes messages by design",
            "a system setting that limits how much usage history is retained",
        ],
        keywords=["normal", "privacy", "incognito", "private", "ephemeral", "expiring",
                  "feature", "default", "benign", "retention"],
    ),

    # ======================= FORENSIC PRINCIPLES =========================
    KnowledgeCard(
        card_id="FP-01",
        title="Principle: missing is not the same as deleted (W1)",
        category="forensic_principle",
        summary=(
            "An expected artifact that is absent is a question, not a conclusion. Before "
            "treating absence as anti-forensic removal, weigh the innocent explanations: it "
            "was never created, it was removed by normal use (uninstall/reboot), or the "
            "acquisition simply did not capture it."
        ),
        indicators=[
            "an artifact that SHOULD exist given other evidence, but does not",
            "weigh: acquisition limit vs never-existed vs normal removal vs deliberate removal",
        ],
        keywords=["missing", "absent", "absence", "expected", "gap", "found", "deleted",
                  "removal", "acquisition", "limit", "innocent"],
    ),
    KnowledgeCard(
        card_id="FP-02",
        title="Principle: independent corroboration strengthens a claim",
        category="forensic_principle",
        summary=(
            "The same fact observed in two or more independent artifacts is much stronger than "
            "the same fact seen once. Two artifacts that disagree is a conflict that must be "
            "explained before relying on either."
        ),
        indicators=[
            "a single fact appearing in two or more unrelated sources (corroboration)",
            "two sources asserting different values for the same thing (conflict)",
        ],
        keywords=["corroborate", "corroboration", "independent", "sources", "agree",
                  "conflict", "consistency", "cross", "confirm", "strength"],
    ),
]