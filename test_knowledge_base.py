"""
Test the knowledge base (box 6.2) — NO LLM, NO GPU.

PART 1: retrieval returns the most relevant card for a question.
PART 2: category lookup works.
PART 3: the rendered prompt block is labelled as general knowledge (not evidence).
PART 4: THE GUARDRAIL — no card mentions any known anti-forensic APP NAME.
        (This is what keeps the detector behavior-based, not a signature matcher.)
"""
from knowledge_base import build_knowledge_base

kb = build_knowledge_base()
print(f"Knowledge base loaded: {len(kb.all_cards())} cards\n")

print("PART 1 — retrieval picks the relevant card")
# a question about repeatedly overwritten, now-missing files should surface wiping
top = kb.retrieve("files were overwritten several times and are now missing", k=3)
print("  query -> top cards:", [(c.card_id, c.category) for c in top])
assert top, "expected at least one card"
# robust check: a wiping card is among the top results (keyword retrieval is approximate)
assert any(c.category == "artifact_wiping" for c in top), "expected a wiping card in the top results"
assert top[0].category == "artifact_wiping", f"expected wiping first after weighting, got {top[0].category}"

# a question about whether clearing cache is normal should surface a normal baseline
norm = kb.retrieve("is it normal for an app to clear its cache", k=3)
print("  query -> top cards:", [c.card_id for c in norm])
assert any(c.category == "normal_baseline" for c in norm), "expected a normal-baseline card"
print("  PART 1 PASS\n")

print("PART 2 — category lookup")
wiping = kb.by_category("artifact_wiping")
print("  artifact_wiping cards:", [c.card_id for c in wiping])
assert wiping and all(c.category == "artifact_wiping" for c in wiping)
print("  PART 2 PASS\n")

print("PART 3 — prompt block is labelled general, not evidence")
block = kb.as_prompt_block(top)
print("  first line:", block.splitlines()[0])
assert "NOT evidence" in block
print("  PART 3 PASS\n")

print("PART 4a — taxonomy: categories are from the allowed set; encryption is under DH")
ALLOWED = {"artifact_wiping", "trail_obfuscation", "data_hiding",
           "presence_installation", "normal_baseline", "forensic_principle"}
bad_cats = sorted({c.category for c in kb.all_cards()} - ALLOWED)
print("  unexpected categories:", bad_cats)
assert not bad_cats, f"card(s) use a category outside the taxonomy: {bad_cats}"
# encryption must NOT be its own category — it is a sub-type of data_hiding
assert "encryption" not in {c.category for c in kb.all_cards()}, "encryption must live under data_hiding"
enc_hits = kb.retrieve("encrypted container keystore", k=3)
assert any(c.category == "data_hiding" for c in enc_hits), "encryption query should surface a data_hiding card"
print("  encryption query -> top cards:", [(c.card_id, c.category) for c in enc_hits])
print("  PART 4a PASS\n")

print("PART 4 — GUARDRAIL: no app names anywhere in the knowledge base")
# the ground-truth app names live ONLY in the evaluation harness; the KB must be clean.
APP_NAMES = [
    "androideraser", "androshredder", "ishredder", "remofileeraser", "safedelete",
    "sdelete", "securedelete", "shredder", "shreddit", "wipefiles", "zerdava",
    "zerofill", "cleanerscope",
]
offenders = []
for c in kb.all_cards():
    blob = " ".join([c.card_id, c.title, c.category, c.summary,
                     " ".join(c.indicators), " ".join(c.keywords)]).lower()
    for name in APP_NAMES:
        if name in blob:
            offenders.append((c.card_id, name))
print("  app-name offenders:", offenders)
assert not offenders, f"KB leaked app name(s): {offenders}"
print("  PART 4 PASS — knowledge base is behavior-based, no app names\n")

print("ALL KNOWLEDGE-BASE TESTS PASSED")