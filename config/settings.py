"""Global configuration: model, paths, and step budget."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

MODEL_NAME = "claude-sonnet-5"

AUDIT_STORE_DIR = BASE_DIR / "audit_store"
DATA_DIR = BASE_DIR / "data"

# Hard cap on plan->validate->execute->observe iterations per case.
MAX_STEPS = 25
