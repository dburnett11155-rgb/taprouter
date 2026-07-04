"""writer.py — Scribe's brain. Local Qwen writes an SEO affiliate article.
FTC disclosure is injected by CODE, never left to the model."""
import json, requests

OLLAMA = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen2.5:3b"
DISCLOSURE = ("*Disclosure: This article contains affiliate links. "
              "If you purchase through them, the author may earn a commission at no extra cost to you.*")

SYSTEM = """You are Scribe, an SEO content writer. You receive a topic, a target keyword,
and one or more affiliate product links. Write a helpful, factual article.
Rules:
- 500-700 words, markdown, one H1, several H2 sections.
- Weave each affiliate link in naturally as [product name](url) where it genuinely helps the reader.
- Honest tone. No fake superlatives, no invented statistics, no fabricated reviews.
- Do NOT write any disclosure line; it is added separately.
Return ONLY valid JSON: {"title": "...", "article_markdown": "..."}"""

def write_article(topic: str, keyword: str, links: list[dict]) -> dict:
    prompt = json.dumps({"topic": topic, "target_keyword": keyword, "affiliate_links": links})
    r = requests.post(OLLAMA, json={
        "model": MODEL, "system": SYSTEM, "prompt": prompt,
        "format": "json", "stream": False,
        "options": {"temperature": 0.7, "num_predict": 1600},
    }, timeout=600)
    r.raise_for_status()
    out = json.loads(r.json()["response"])
    out["article_markdown"] = DISCLOSURE + "\n\n" + out["article_markdown"]
    return out

if __name__ == "__main__":
    art = write_article(
        "best budget mechanical keyboards for beginners",
        "budget mechanical keyboard",
        [{"name": "Keychron C1", "url": "https://example.com/aff/keychron-c1"}],
    )
    print(art["title"])
    print(art["article_markdown"][:400], "...")
