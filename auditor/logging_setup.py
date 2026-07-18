"""Centralized logging — every run gets a stamped dir under auditor/logs/run_<ts>/.
Raw tool stdout/stderr, structured findings, and LLM I/O all land here for human audit.
Blueprint constraint: comprehensive error logging, one place, easy to inspect."""
import logging, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config

def new_run_dir() -> Path:
    run_id = time.strftime("run_%Y%m%d_%H%M%S")
    d = config.LOG_DIR / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d

def get_logger(run_dir: Path, name: str = "crucible") -> logging.Logger:
    log = logging.getLogger(f"{name}.{run_dir.name}")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    # File: everything. Console: info+.
    fh = logging.FileHandler(run_dir / "crucible.log")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("  %(message)s"))
    log.addHandler(fh); log.addHandler(ch)
    return log

def save_raw(run_dir: Path, name: str, content: str):
    """Dump a raw artifact (tool output, prompt, LLM response) to the run dir."""
    (run_dir / name).write_text(content or "")
