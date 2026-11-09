"""
test_llm_reasoner.py  —  RUN THIS ON THE VM (needs Ollama + a pulled model).

Confirms three things, using NO capture files:
  1. We can reach the local model server (Ollama) and get a reply.
  2. The model returns something our parser turns into an AgentAction.
  3. The model picks one of OUR real tools (not an invented one).

Pick the model with an env var (the fast one while we build):
    OLLAMA_MODEL=qwen2.5:7b-instruct python test_llm_reasoner.py
Switch to the strong one for a heavier check:
    OLLAMA_MODEL=qwen2.5-coder:32b python test_llm_reasoner.py
"""
import os
from engine.llm_reasoner import LLMReasoner
from engine.bounded_loop import ActionKind
from tools.registry import build_catalog

model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
print(f"Using model: {model}")
print(f"Ollama at  : {os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')}")
print("-" * 70)

catalog = build_catalog()
reasoner = LLMReasoner(catalog)   # builds ChatOllama from env vars

# A tiny synthetic 'current case state' — no real artifacts needed.
context = (
    "=== CASE MEMORY (step 1) ===\n"
    "Open hypotheses (0):\n"
    "Confirmed findings (0):\n"
    "Suspicious absences (0):\n"
    "Recent log:\n  (nothing yet)\n\n"
    "Available tools:\n" + catalog.describe_for_prompt() + "\n\n"
    "Last observation:\n"
    "Investigation started. A capture folder for one Android device is available. "
    "No evidence gathered yet."
)

print("Asking the model for its first action...\n")
action = reasoner.next_action(context)

print("RAW MODEL REPLY:")
print(reasoner.last_raw_reply[:1500])
print("-" * 70)
print("MAPPED AgentAction:")
print("  thought   :", action.thought)
print("  kind      :", action.kind.value)
print("  tool_name :", action.tool_name)
print("  tool_args :", action.tool_args)
print("-" * 70)

assert action.kind in (ActionKind.CALL_TOOL, ActionKind.CONCLUDE)
if action.kind == ActionKind.CALL_TOOL:
    assert action.tool_name in catalog.names(), (
        f"model chose '{action.tool_name}', NOT an allowed tool "
        f"(allowed: {catalog.names()}) — the gate would reject it"
    )
    print(f"OK  model picked a REAL tool: {action.tool_name}")
else:
    print("OK  model chose to conclude (acceptable on an empty case)")

print("\nSmoke test passed — model connection and JSON parsing both work.")