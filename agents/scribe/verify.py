"""verify.py — request signature verification (transport integrity + freshness).
V1 scope: confirms the request wasn't tampered in transit and isn't a replay.
Buyer identity remains proven by escrow state on-chain, not by this signature.
"""
import time
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak

MAX_AGE_SECONDS = 300

def check_signature(headers, body_bytes: bytes) -> dict:
    """Returns {"ok": bool, "signer": str|None, "reason": str}. Never raises."""
    try:
        ts = headers.get("X-Tap-Timestamp")
        sig = headers.get("X-Tap-Signature")
        claimed = headers.get("X-Tap-Signer")
        if not (ts and sig and claimed):
            return {"ok": False, "signer": None, "reason": "unsigned"}
        if abs(time.time() - int(ts)) > MAX_AGE_SECONDS:
            return {"ok": False, "signer": None, "reason": "stale"}
        digest = keccak(f"tapmarket-v1:{ts}:".encode() + body_bytes)
        recovered = Account.recover_message(encode_defunct(digest), signature=sig)
        if recovered.lower() != claimed.lower():
            return {"ok": False, "signer": recovered, "reason": "signer mismatch"}
        return {"ok": True, "signer": recovered, "reason": "valid"}
    except Exception as e:
        return {"ok": False, "signer": None, "reason": f"error: {e}"}

import os
ENFORCE = os.environ.get("TAP_AUTH_ENFORCE", "") == "1"

def gate(headers, body_bytes):
    """Returns (allow, verdict). Observe mode (default): always allow, log verdict.
    Enforce mode (TAP_AUTH_ENFORCE=1): allow only valid signatures."""
    v = check_signature(headers, body_bytes)
    return (v["ok"] if ENFORCE else True), v
