// brain.js — Echo's planner. Local Qwen decides which specialist a task needs.
// Zero API cost. Logs every decision to decisions.jsonl (judgment audit trail).
import { appendFileSync } from "fs";

const OLLAMA = "http://127.0.0.1:11434/api/generate";
const MODEL = "qwen2.5:3b";

// The capability catalog. Hardcoded for now — becomes the registry in Phase 3.
export const CATALOG = [
  {
    id: "hermes",
    listingId: 1,
    pricePerUse: "0.5 USDC",
    description: "On-chain risk oracle for BASE SEPOLIA ONLY. Assesses any EVM address on Base Sepolia and returns a structured risk report. Cannot check other chains like Arbitrum or mainnet.",
    input: "an 0x EVM address",
  },
];

const SYSTEM = `You are Echo, an autonomous orchestrator. You receive a task and a catalog of specialist agents you can hire.
Rules:
- Pick a specialist ONLY if it genuinely fits the task.
- Extract the exact input the specialist needs from the task text.
- If no specialist fits, or the input is missing, refuse.
Return ONLY valid JSON: {"decision":"hire"|"refuse","specialist":"<id or null>","input":"<extracted input or null>","reason":"<one sentence>"}`;

export async function plan(task) {
  const prompt = `Task: ${task}\n\nCatalog:\n${JSON.stringify(CATALOG, null, 2)}`;
  const res = await fetch(OLLAMA, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model: MODEL, system: SYSTEM, prompt, format: "json", stream: false, options: { temperature: 0.1 } }),
  });
  const body = await res.json();
  const decision = JSON.parse(body.response);
  appendFileSync("decisions.jsonl", JSON.stringify({ ts: new Date().toISOString(), task, decision }) + "\n");
  return decision;
}

// Standalone test: node brain.js "some task"
if (process.argv[1].endsWith("brain.js")) {
  const task = process.argv[2] || "Is 0x036CbD53842c5426634e7929541eC2318f3dCF7e safe to interact with?";
  console.log("[echo brain] task:", task);
  console.log("[echo brain] decision:", await plan(task));
}
