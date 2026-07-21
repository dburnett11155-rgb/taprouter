"""llm_client.py — provider dispatch for Crucible's certification engine.
Re-exports call_json from the provider named by config.LLM_PROVIDER, so every agent
(red/white/judge/exploit_generator) imports ONE thing and the engine is swapped in one
place. DeepSeek is primary (no daily RPD cap); Gemini reachable by flipping LLM_PROVIDER.
The badge is pinned to whichever provider certifies — keep this single-sourced."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

if getattr(config, "LLM_PROVIDER", "gemini") == "deepseek":
    from adversarial.deepseek_client import call_json, DeepSeekError as LLMError
else:
    from adversarial.gemini_client import call_json, GeminiError as LLMError

__all__ = ["call_json", "LLMError"]
