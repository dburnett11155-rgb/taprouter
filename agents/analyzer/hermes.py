"""hermes.py — Hermes, the on-chain risk oracle. Local Qwen brain + on-chain facts.

Takes an address, pulls verified on-chain facts, and returns a structured risk
assessment. Zero API cost (runs on-Pi). Advisory only: Hermes scores and reports,
it never holds keys, signs, or writes state.
"""
import json
from dataclasses import asdict
from onchain import fetch_facts
from brain import ask_json

SYSTEM_PROMPT = """You are Hermes, an on-chain risk oracle. You receive verified,
factual on-chain data about a blockchain address and produce a disciplined risk
assessment. Rules:
- Ground every statement in the facts provided. Never invent data.
- Absence of data (null/zero) is NOT evidence of risk; say "insufficient data" instead.
- Be conservative and specific. A verified token contract is normal, not suspicious.
- risk_score reflects ONLY what the facts support.

Return ONLY valid JSON with exactly these keys:
{
  "address_type": "EOA" | "ERC20_token" | "other_contract",
  "risk_score": "low" | "medium" | "high" | "unknown",
  "risk_factors": ["concrete factor grounded in facts", "..."],
  "positive_signals": ["concrete reassuring factor", "..."],
  "summary": "one or two sentence plain-English risk summary",
  "confidence": "low" | "medium" | "high"
}"""


def assess(address: str) -> dict:
    facts = fetch_facts(address)

    # Threat intelligence + known-address layer (code-enforced)
    from onchain import threat_check, KNOWN
    known_note = KNOWN.get(address.lower())
    tflags = threat_check(address)
    tflags.pop("contract_address", None)  # informational, not a threat
    fdict = asdict(facts)
    fdict["known_identity"] = known_note
    fdict["threat_intel_flags"] = tflags or "none found (GoPlus, Base mainnet feed)"
    facts_json = json.dumps(fdict, indent=2)

    assessment = ask_json(
        SYSTEM_PROMPT,
        f"On-chain facts for the address:\n{facts_json}\n\nProduce the risk assessment.",
    )

    SEVERE = {"phishing_activities", "blacklist_doubt", "stealing_attack", "money_laundering",
              "cybercrime", "malicious_mining_activities", "honeypot_related_address"}
    hits = sorted(SEVERE & set(tflags))
    if hits:
        assessment["risk_score"] = "high"
        assessment["risk_factors"] = [f"THREAT INTEL: flagged for {h}" for h in hits] + assessment.get("risk_factors", [])
        assessment["summary"] = "DO NOT INTERACT - threat intelligence flags this address. " + assessment.get("summary", "")
    if known_note:
        assessment.setdefault("risk_factors", []).insert(0, f"KNOWN ADDRESS: {known_note}")
        assessment["address_type"] = "known_special_address"
    return {"facts": fdict, "assessment": assessment}


if __name__ == "__main__":
    import sys, time
    target = sys.argv[1] if len(sys.argv) > 1 else "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
    print(f"Hermes assessing {target} ...")
    t0 = time.time()
    result = assess(target)
    dt = time.time() - t0
    print(json.dumps(result, indent=2))
    print(f"\n(assessed in {dt:.1f}s)")
