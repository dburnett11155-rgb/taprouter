"""brain.py — local LLM via Ollama (Qwen 2.5 3B). Zero API cost, runs on-Pi."""
import json
import requests

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen2.5:3b"


def ask_json(system_prompt: str, user_prompt: str, timeout: int = 120) -> dict:
    """Send a prompt to local Qwen, expect JSON back, parse and return it."""
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
