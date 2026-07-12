"""brain.py — local LLM via Ollama (Qwen 2.5 3B). Zero API cost, runs on-Pi."""
import json
import os
import requests

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
MODEL = "qwen2.5:3b"


def ask_json(system_prompt: str, user_prompt: str, timeout: int = 120) -> dict:
    """Gemini fast path when key present; local Qwen fallback. JSON out either way."""
    if GEMINI_KEY:
        try:
            r = requests.post(f"{GEMINI_URL}?key={GEMINI_KEY}", json={
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"parts": [{"text": user_prompt}]}],
                "generationConfig": {"temperature": 0.2, "response_mime_type": "application/json"},
            }, timeout=30)
            r.raise_for_status()
            out = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            print("[hermes] generated via gemini", flush=True)
            return out
        except Exception as e:
            print(f"[hermes] gemini failed ({e}) — falling back to local model", flush=True)
    payload = {
        "model": MODEL,
        "system": system_prompt,
        "prompt": user_prompt,
        "format": "json",        # Ollama constrains output to valid JSON
        "stream": False,
        "options": {"temperature": 0.2},
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    raw = body.get("response", "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"Qwen returned non-JSON:\n{raw}")


if __name__ == "__main__":
    out = ask_json(
        "You are a test. Return JSON only.",
        'Return {"hello": "world", "n": 42}',
    )
    print("parsed:", out)
