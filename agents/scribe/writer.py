"""writer.py — Scribe's brain. Local Qwen writes an SEO affiliate article.
FTC disclosure is injected by CODE, never left to the model."""
import json, os, os, requests

OLLAMA = "http://127.0.0.1:11434/api/generate"
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"

def _generate_gemini(system: str, prompt: str) -> dict:
    r = requests.post(f"{GEMINI_URL}?key={GEMINI_KEY}", json={
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "response_mime_type": "application/json", "maxOutputTokens": 4000},
    }, timeout=30)
    r.raise_for_status()
    return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
MODEL = "qwen2.5:3b"
DISCLOSURE = ("*Disclosure: This article contains affiliate links. "
              "If you purchase through them, the author may earn a commission at no extra cost to you.*")

SYSTEM = """You are Scribe, an SEO content writer. You receive a topic, a target keyword,
and one or more affiliate product links. Write a helpful, factual article.
Rules:
- 500-700 words, markdown, one H1, several H2 sections.
- Weave each affiliate link in naturally as [product name](url) where it genuinely helps the reader.
- Honest tone. No fake superlatives, no invented statistics, no fabricated reviews.
- If verified_facts_from_live_web_search is provided, GROUND the article in those facts: use real product names, real prices, real details from the facts. NEVER invent products or placeholder names like "Product 1".
- Do NOT write any disclosure line; it is added separately.
Return ONLY valid JSON: {"title": "...", "article_markdown": "..."}"""

def research(query: str) -> str:
    """Live web search via Tavily. Returns a compact facts digest for the writer."""
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        return ""
    try:
        r = requests.post("https://api.tavily.com/search", json={
            "api_key": key, "query": query, "max_results": 5,
            "search_depth": "basic", "include_answer": True,
        }, timeout=30)
        r.raise_for_status()
        j = r.json()
        facts = [f"- {res['title']}: {res['content'][:300]}" for res in j.get("results", [])]
        answer = j.get("answer", "")
        return (f"SUMMARY: {answer}\n" if answer else "") + "\n".join(facts)
    except Exception as e:
        print(f"[scribe] research failed ({e}) — writing without live data", flush=True)
        return ""

def write_article(topic: str, keyword: str, links: list[dict]) -> dict:
    facts = research(f"{topic} {keyword} 2026")
    prompt = json.dumps({"topic": topic, "target_keyword": keyword, "affiliate_links": links,
                         "verified_facts_from_live_web_search": facts or "none available"})
    out = None
    if GEMINI_KEY:
        try:
            out = _generate_gemini(SYSTEM, prompt)
            print("[scribe] generated via gemini", flush=True)
        except Exception as e:
            print(f"[scribe] gemini failed ({e}) — falling back to local model", flush=True)
    if out is None:
     r = requests.post(OLLAMA, json={
        "model": MODEL, "system": SYSTEM, "prompt": prompt,
        "format": "json", "stream": False,
        "options": {"temperature": 0.7, "num_predict": 3000},
     }, timeout=600)
     r.raise_for_status()
     try:
        out = json.loads(r.json()["response"])
     except json.JSONDecodeError:
        print("[scribe] malformed JSON from model — retrying once", flush=True)
        r = requests.post(OLLAMA, json={
            "model": MODEL, "system": SYSTEM, "prompt": prompt,
            "format": "json", "stream": False,
            "options": {"temperature": 0.4, "num_predict": 3000},
        }, timeout=600)
        r.raise_for_status()
        out = json.loads(r.json()["response"])
    md = out["article_markdown"]
    # Strip hallucinated placeholder links
    import re
    md = re.sub(r"\[([^\]]+)\]\(https?://(?:www\.)?example\.com[^)]*\)", r"\1", md)
    # Contract enforcement: every buyer link must appear; append any the model dropped
    missing = [l for l in links if l["url"] not in md]
    if missing:
        rows = "\n".join(f"- [{l['name']}]({l['url']})" for l in missing)
        md += f"\n\n## Where to Buy\n{rows}"
    out["article_markdown"] = DISCLOSURE + "\n\n" + md
    return out

if __name__ == "__main__":
    art = write_article(
        "best budget mechanical keyboards for beginners",
        "budget mechanical keyboard",
        [{"name": "Keychron C1", "url": "https://example.com/aff/keychron-c1"}],
    )
    print(art["title"])
    print(art["article_markdown"][:400], "...")
