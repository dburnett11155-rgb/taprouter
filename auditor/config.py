"""Crucible config — paths, tool settings, model tiers. Single source of truth."""
import os
from pathlib import Path

ROOT = Path("/home/dburnett11155/taprouter")
AUDITOR = ROOT / "auditor"
LOG_DIR = AUDITOR / "logs"
OUT_DIR = AUDITOR / "out"
KNOWN_VULNS = AUDITOR / "known_vulns"

# Default audit target: TapMarket's own source (dogfood). Overridable per-run.
DEFAULT_TARGET = ROOT / "contracts" / "src"
FOUNDRY_ROOT = ROOT / "contracts"          # where foundry.toml lives (for src remappings)

# Skip these — deploy scripts and scaffolding are not audit targets.
SKIP_PATTERNS = ("/broadcast/", "/script/", "/lib/", "/test/", "Counter.sol")

# Tool binaries (resolved from auditor venv / cargo bin; None = not installed, skip gracefully)
AUDITOR_VENV = AUDITOR / "venv"
SLITHER_BIN = str(AUDITOR_VENV / "bin" / "slither")
MYTHRIL_BIN = str(AUDITOR_VENV / "bin" / "myth")
ADERYN_BIN = os.path.expanduser("~/.cargo/bin/aderyn")   # Rust; may be absent on ARM
ANVIL_BIN = os.path.expanduser("~/.foundry/bin/anvil")

# Timeouts (seconds). Mythril is the slow symbolic pass — long leash, and optional.
SLITHER_TIMEOUT = 180
ADERYN_TIMEOUT = 180
MYTHRIL_TIMEOUT = 1800          # 30 min; ARM symbolic execution is brutal
MYTHRIL_ENABLED = False         # opt-in via --deep; Slither+Aderyn are the fast default

# Gemini model tiers by role (rolling aliases — never hard-pin a version)
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL_TRIAGE = "gemini-flash-latest"    # ingestion: normalize, dedupe, summarize findings
MODEL_DEBATE = "gemini-pro-latest"      # Red/White/Judge: exploit reasoning + patch design
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Severity ordering — tool findings are GROUND TRUTH; the LLM triages, never overturns.
SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1, "informational": 0, "optimization": 0}
BADGE_BLOCKS_ON = ("high", "medium")   # any of these unresolved => no pass-badge
