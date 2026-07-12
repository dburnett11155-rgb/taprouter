#!/usr/bin/env node
// TapMarket MCP server — lets any MCP client (Claude, OpenClaw, etc.) hire paid
// specialists on TapMarket. Crypto hidden; charges and limits always visible.
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { createPublicClient, http, parseAbi, encodeFunctionData, formatUnits } from "viem";
import { baseSepolia } from "viem/chains";
import { createKernelAccountClient } from "@zerodev/sdk";
import { KERNEL_V3_1, getEntryPoint } from "@zerodev/sdk/constants";
import { deserializePermissionAccount } from "@zerodev/permissions";
import { config } from "dotenv";
import { appendFileSync } from "fs";
import { homedir } from "os";
import { join } from "path";
import { CATALOG as FALLBACK_CATALOG } from "./catalog.js";

const SHAPES = {
  address: (input, buyer) => ({ address: input.address, buyer }),
  passthrough: (input, buyer) => ({ ...input, buyer }),
};
let CATALOG = FALLBACK_CATALOG;
try {
  const r = await fetch("https://registry.tappayment.io/registry", { signal: AbortSignal.timeout(5000) });
  const reg = await r.json();
  if (Array.isArray(reg.specialists) && reg.specialists.length) {
    CATALOG = reg.specialists.map(sp => ({ ...sp, shape: SHAPES[sp.shapeKind] ?? SHAPES.passthrough }));
    console.error(`tapmarket: live registry loaded (${CATALOG.length} specialists)`);
  }
} catch { console.error("tapmarket: registry unreachable — using built-in catalog"); }
import { ZERODEV_RPC as ZRPC } from "./init-lib.js";
import { loadWallet } from "./wallet-store.js";
import { readFileSync } from "fs";

const { wallet, path: WALLET_FILE } = loadWallet();
if (!wallet) {
  console.error("No wallet found. Run: npx tapmarket-connect setup");
  process.exit(1);
}
if (wallet.authKey) {
  console.error("tapmarket: auth signing with dedicated authKey");
} else if (wallet.ownerKey) {
  console.error("tapmarket: auth LEGACY — signing with plaintext ownerKey (run any owner command to migrate)");
} else {
  console.error("tapmarket: WARNING — no authKey and ownerKey is encrypted; hires will be sent UNSIGNED (observe mode tolerates this; run an owner command to add authKey)");
}
const AUTH_SIGNING_KEY = wallet.authKey ?? wallet.ownerKey ?? null;

config({ path: new URL("../.env.local", import.meta.url).pathname, quiet: true });

const TAP_MARKET = "0xBfd085f192d2246F1BFBe386DF399335dc894f2c";
const USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e";
const ZERODEV_RPC = ZRPC;
// routes now come from catalog entries (endpoint + shape)

const marketAbi = parseAbi(["function buyPack(uint256 listingId, uint256 numUses, uint64 capPerPeriod)", "function escrows(uint256,address) view returns (uint256 balance, uint256 usesPurchased, uint256 usesSettled, uint64 capPerPeriod, uint64 periodStart, uint64 usedThisPeriod, uint64 purchaseTime)"]);
const usdcAbi = parseAbi(["function approve(address,uint256)", "function balanceOf(address) view returns (uint256)"]);
const publicClient = createPublicClient({ chain: baseSepolia, transport: http("https://sepolia.base.org") });
const account = await deserializePermissionAccount(
  publicClient, getEntryPoint("0.7"), KERNEL_V3_1, wallet.sessionApproval
);
const kernelClient = createKernelAccountClient({ account, chain: baseSepolia, bundlerTransport: http(ZERODEV_RPC) });

const LIMITS_TEXT = `Spending limits (enforced by smart contract, not by this software):
- This wallet can ONLY spend on TapMarket listings and approve USDC to TapMarket. No other transfers are possible, even if this server is compromised.
- Revoke anytime: the account owner can disable the session key with one transaction, instantly freezing all spending.
- Every payment settles on-chain with a public receipt.`;

function shortAddr() { return account.address.slice(0, 6) + "…" + account.address.slice(-4); }
async function balanceLine() {
  const bal = await publicClient.readContract({ address: USDC, abi: usdcAbi, functionName: "balanceOf", args: [account.address] });
  return `Wallet ${shortAddr()} (this machine): $${formatUnits(bal, 6)} USDC`;
}

function formatWork(work) {
  if (work && typeof work === "object" && typeof work.risk_score === "string") {
    const icon = { low: "LOW RISK", medium: "MEDIUM RISK", high: "HIGH RISK", unknown: "UNKNOWN" }[work.risk_score] ?? work.risk_score.toUpperCase();
    const factors = (work.risk_factors ?? []).map(f => `- ${f}`).join("\n") || "- none identified";
    return `## Risk Report: ${icon}\n\n${work.summary ?? ""}\n\n**Findings:**\n${factors}`
      + (work.address_type ? `\n\n**Address type:** ${work.address_type}` : "")
      + "\n\n---\nPresent this risk report to the user clearly. Keep the risk level prominent.";
  }
  if (work && typeof work === "object" && typeof work.article_markdown === "string") {
    let t = (work.title ? `# ${work.title}\n\n` : "") + work.article_markdown;
    if (work.title && work.article_markdown.includes(work.title)) t = work.article_markdown;
    return t + "\n\n---\nShow the user the COMPLETE article above verbatim — do not summarize or shorten it. It is their purchased work product.";
  }
  return JSON.stringify(work, null, 2);
}

const server = new Server({ name: "tapmarket", version: "0.1.0" }, { capabilities: { tools: {} } });

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    { name: "list_specialists", description: "List hireable specialist agents on TapMarket with prices.", inputSchema: { type: "object", properties: {} } },
    { name: "hire_specialist", description: "Hire a specialist for one job. Pays the listed price from the connected wallet (spending is contract-limited to TapMarket only). Fast jobs return the work product directly. Slower jobs return a job_id — use check_job with it after ~30 seconds to retrieve the finished work. Never call hire_specialist again for the same request; that would charge the user twice.", inputSchema: { type: "object", properties: {
      specialist: { type: "string", description: "specialist id from list_specialists" },
      input: { type: "object", description: "hermes: {address: '0x..'}; scribe: {topic, keyword, links:[{name,url}]}" },
    }, required: ["specialist", "input"] } },
    { name: "get_balance", description: "Show wallet balance and spending limits.", inputSchema: { type: "object", properties: {} } },
    { name: "check_job", description: "Retrieve the finished work for a job_id returned by hire_specialist. Free — no charge. If still processing, wait ~30 seconds and call again.", inputSchema: { type: "object", properties: {
      specialist: { type: "string", description: "specialist id the job was hired from" },
      job_id: { type: "string" },
    }, required: ["specialist", "job_id"] } },
    { name: "rate_specialist", description: "Rate a completed hire (1-5) with a short critique. Do this after reviewing each work product — ratings are shown to all future buyers and help good specialists rise.", inputSchema: { type: "object", properties: {
      specialist: { type: "string" }, score: { type: "number", description: "1-5" },
      critique: { type: "string", description: "one line on quality" }, settleTx: { type: "string", description: "settlement tx from the hire" },
    }, required: ["specialist", "score"] } },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  const { name, arguments: args } = req.params;
  try {
    if (name === "list_specialists") {
      let rep = {};
      try { rep = await (await fetch("https://fund.tappayment.io/reputation", { signal: AbortSignal.timeout(4000) })).json(); } catch {}
      const lines = CATALOG.map(s => {
        const r = rep[s.id];
        const badge = r ? ` [rated ${r.avg}/5 over ${r.jobs_rated} job${r.jobs_rated === 1 ? "" : "s"}]` : " [no ratings yet]";
        return `- ${s.id} (${s.pricePerUse}/use)${badge}: ${s.description}`;
      }).join("\n");
      return { content: [{ type: "text", text: `${lines}\n\n${await balanceLine()}\n\n${LIMITS_TEXT}` }] };
    }
    if (name === "rate_specialist") {
      const r = await fetch("https://fund.tappayment.io/feedback", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(args) });
      const j = await r.json();
      return { content: [{ type: "text", text: j.recorded ? `Rating recorded: ${args.specialist} ${args.score}/5. Thank you — this is visible to all buyers.` : "Rating not recorded (bad input)." }] };
    }
    if (name === "get_balance") {
      return { content: [{ type: "text", text: `${await balanceLine()}\n\n${LIMITS_TEXT}` }] };
    }
    if (name === "hire_specialist") {
      const spec = CATALOG.find(s => s.id === args.specialist);
      if (!spec) return { content: [{ type: "text", text: `Unknown specialist '${args.specialist}'. Use list_specialists.` }], isError: true };
      const route = { url: spec.endpoint, body: spec.shape };
      // Retry guard: if a job for this specialist was submitted in the last 10 min and never delivered, resume it instead of re-charging
      try {
        const recent = readFileSync(join(homedir(), ".tapmarket", "inflight.jsonl"), "utf8").trim().split("\n").map(l => JSON.parse(l))
          .filter(j => j.specialist === spec.id && Date.now() - j.ts < 10 * 60 * 1000);
        if (recent.length) {
          const j = recent[recent.length - 1];
          const pr = await fetch(spec.resultEndpoint + j.job_id, { headers: { "Authorization": `Bearer ${process.env.TAP_SERVICE_TOKEN ?? "public-testnet-v01"}` } });
          const pj = await pr.json();
          if (pj.status === "done") {
            const work = pj.assessment ?? pj.article ?? pj;
            return { content: [{ type: "text", text: `Found your recently completed job (no new charge).${pj.settleTx ? `\nSettlement receipt: https://sepolia.basescan.org/tx/${pj.settleTx}` : ""}\n\nWORK PRODUCT:\n\n${formatWork(work)}` }] };
          }
          if (pj.status === "working") {
            return { content: [{ type: "text", text: `A job for this request is already in progress (no new charge) — job_id: ${j.job_id}. Call check_job with specialist "${spec.id}" in ~30 seconds.` }] };
          }
        }
      } catch {}
      const esc = await publicClient.readContract({ address: TAP_MARKET, abi: marketAbi, functionName: "escrows", args: [BigInt(spec.listingId), account.address] });
      let payTxText = "used existing prepaid pack (no new charge)";
      let chargedText = `NO NEW CHARGE (prepaid pack used) — value: ${spec.pricePerUse}`;
      if (esc[1] <= esc[2]) {
      const hash = await kernelClient.sendUserOperation({
        callData: await account.encodeCalls([
          { to: USDC, value: 0n, data: encodeFunctionData({ abi: usdcAbi, functionName: "approve", args: [TAP_MARKET, BigInt(spec.priceUnits)] }) },
          { to: TAP_MARKET, value: 0n, data: encodeFunctionData({ abi: marketAbi, functionName: "buyPack", args: [BigInt(spec.listingId), 1n, 10n] }) },
        ]),
      });
      const receipt = await kernelClient.waitForUserOperationReceipt({ hash });
      payTxText = `https://sepolia.basescan.org/tx/${receipt.receipt.transactionHash}`;
      chargedText = `CHARGED: ${spec.pricePerUse} to ${spec.id}`;
      }
      const bodyText = JSON.stringify(route.body(args.input, account.address));
      const { keccak256, toBytes } = await import("viem");
      const { privateKeyToAccount } = await import("viem/accounts");
      let sigHeaders = {};
      if (AUTH_SIGNING_KEY) {
        const ts = Math.floor(Date.now() / 1000);
        const digest = keccak256(toBytes(`tapmarket-v1:${ts}:${bodyText}`));
        const reqSig = await privateKeyToAccount(AUTH_SIGNING_KEY).signMessage({ message: { raw: digest } });
        sigHeaders = { "X-Tap-Timestamp": String(ts), "X-Tap-Signature": reqSig, "X-Tap-Signer": privateKeyToAccount(AUTH_SIGNING_KEY).address };
      }
      const res = await fetch(route.url, { method: "POST", headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${process.env.TAP_SERVICE_TOKEN ?? "public-testnet-v01"}`,
        ...sigHeaders,
      }, body: bodyText });
      let out = await res.json();
      if (spec.async && out.job_id) {
        try { appendFileSync(join(homedir(), ".tapmarket", "inflight.jsonl"), JSON.stringify({ ts: Date.now(), specialist: spec.id, job_id: out.job_id }) + "\n"); } catch {}
        const deadline = Date.now() + 45 * 1000;
        while (Date.now() < deadline) {
          await new Promise(r => setTimeout(r, 5000));
          const pr = await fetch(spec.resultEndpoint + out.job_id, { headers: { "Authorization": `Bearer ${process.env.TAP_SERVICE_TOKEN ?? "public-testnet-v01"}` } });
          const pj = await pr.json();
          if (pj.status === "done") { out = pj; break; }
          if (pj.status === "failed") { return { content: [{ type: "text", text: `Job failed: ${pj.error}. If payment was taken, the pack remains usable — retry the hire.` }], isError: true }; }
        }
        if (out.job_id && !out.article) return { content: [{ type: "text", text: `Payment complete (${chargedText}). The work is still being produced — job_id: ${out.job_id}. Call check_job with specialist "${spec.id}" and this job_id in about 30 seconds to retrieve it. Do NOT call hire_specialist again — that would charge again.` }] };
      }
      try { appendFileSync(join(homedir(), ".tapmarket", "hires.jsonl"), JSON.stringify({ ts: new Date().toISOString(), specialist: spec.id, charge: spec.pricePerUse, payTx: payTxText, settleTx: out.settleTx }) + "\n"); } catch {}
      const work = out.assessment ?? out.article ?? out;
      const workText = formatWork(work);
      return { content: [{ type: "text", text:
        `${chargedText}\n${await balanceLine()}\nPayment: ${payTxText}\nSettlement receipt: https://sepolia.basescan.org/tx/${out.settleTx}\n\nWORK PRODUCT:\n\n${workText}` }] };
    }
    if (name === "check_job") {
      const spec = CATALOG.find(x => x.id === args.specialist);
      if (!spec?.resultEndpoint) return { content: [{ type: "text", text: `Unknown specialist or no async endpoint: '${args.specialist}'` }], isError: true };
      const pr = await fetch(spec.resultEndpoint + args.job_id, { headers: { "Authorization": `Bearer ${process.env.TAP_SERVICE_TOKEN ?? "public-testnet-v01"}` } });
      const pj = await pr.json();
      if (pj.status === "failed") return { content: [{ type: "text", text: `Job failed: ${pj.error}. Your prepaid pack remains usable — retry the hire.` }], isError: true };
      if (pj.status !== "done") return { content: [{ type: "text", text: `Still processing. Wait ~30 seconds and call check_job again with the same job_id.` }] };
      const work = pj.assessment ?? pj.article ?? pj;
      return { content: [{ type: "text", text: `Job complete.${pj.settleTx ? `\nSettlement receipt: https://sepolia.basescan.org/tx/${pj.settleTx}` : ""}\n\nWORK PRODUCT:\n\n${formatWork(work)}` }] };
    }
    return { content: [{ type: "text", text: `Unknown tool ${name}` }], isError: true };
  } catch (e) {
    return { content: [{ type: "text", text: `Error: ${e.shortMessage ?? e.message}` }], isError: true };
  }
});

await server.connect(new StdioServerTransport());
console.error("tapmarket MCP server ready (stdio)");
