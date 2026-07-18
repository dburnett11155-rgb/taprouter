"""gemini_client.py — controlled LLM caller for Crucible's CERTIFICATION engine.
Runs on OUR Gemini-pro (not the buyer's model) so verdicts are consistent and the badge
means one thing. Native JSON mode, bounded retry, per-call logging to the run dir.
Every request+response is auditable — a security tool's reasoning must be inspectable."""
import json, time, requests, sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

class GeminiError(Exception):
    pass

def _loads_lenient(raw: str):
    """Parse JSON that may have trailing extra data or markdown fences."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"): raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # extract first complete JSON object via brace-matching
        depth, start = 0, None
        for i, c in enumerate(raw):
            if c == "{":
                if start is None: start = i
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    return json.loads(raw[start:i+1])
        raise

def call_json(system: str, user: str, *, model: str = None, run_dir=None,
              label: str = "call", temperature: float = 0.2, max_retries: int = 2) -> dict:
    """Call Gemini expecting strict JSON back. Returns parsed dict.
    Logs full request/response to run_dir if provided. Raises GeminiError on hard failure."""
    model = model or config.MODEL_DEBATE
    key = os.environ.get("GEMINI_API_KEY", "") or config.GEMINI_KEY
    if not key:
        raise GeminiError("GEMINI_API_KEY not in environment — load .env.local before calling")
    url = f"{config.GEMINI_BASE}/{model}:generateContent?key={key}"
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": user}]}],
        "generationConfig": {"temperature": temperature, "response_mime_type": "application/json"},
    }
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=90)
            if r.status_code == 429:  # true rate limit — quota windows are per-MINUTE; back off for real
                retry_after = r.headers.get("Retry-After")
                wait = int(retry_after) if (retry_after and retry_after.isdigit()) else 25 * (attempt + 1)
                last_err = f"429 rate limit (waited {wait}s)"
                if run_dir: _log(run_dir, label, model, system, user, r.text[:500], ok=False, attempt=attempt)
                time.sleep(wait); continue
            if not r.ok:  # 403 etc — surface the real reason, do not blindly retry
                last_err = f"{r.status_code}: {r.text[:300]}"
                if run_dir: _log(run_dir, label, model, system, user, r.text[:500], ok=False, attempt=attempt)
                break
            r.raise_for_status()
            raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            parsed = _loads_lenient(raw)
            # A refusal is NOT a verdict — never let it pass as "no issue found".
            if isinstance(parsed, dict) and "error" in parsed and len(parsed) == 1:
                if any(w in str(parsed["error"]).lower() for w in ("cannot fulfill", "cannot analyze", "safety guidelines", "unable to")):
                    last_err = f"model refused: {parsed['error'][:120]}"
                    if run_dir: _log(run_dir, label, model, system, user, raw, ok=False, attempt=attempt)
                    time.sleep(1 + attempt); continue
            if run_dir:
                _log(run_dir, label, model, system, user, raw, ok=True)
            return parsed
        except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
            last_err = f"{type(e).__name__}: {e}"
            if run_dir:
                _log(run_dir, label, model, system, user, str(e), ok=False, attempt=attempt)
            time.sleep(1 + attempt)
    raise GeminiError(f"{label} failed after {max_retries+1} attempts: {last_err}")

def _log(run_dir, label, model, system, user, response, ok, attempt=0):
    d = Path(run_dir) / "llm_calls"
    d.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%H%M%S")
    (d / f"{ts}_{label}_{'ok' if ok else f'err{attempt}'}.json").write_text(json.dumps({
        "model": model, "label": label, "system": system,
        "user": user[:4000], "response": response[:8000], "ok": ok,
    }, indent=2))

if __name__ == "__main__":
    # Smoke test — prove the controlled engine answers in JSON, no real finding needed.
    out = call_json(
        system="You are a test harness. Reply ONLY with JSON.",
        user='Return exactly {"status":"ok","model_reasoning_works":true}',
        label="smoketest",
    )
    print("gemini_client:", out)
    print("model used:", config.MODEL_DEBATE)
