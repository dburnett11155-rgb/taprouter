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
import { readFileSync, existsSync } from "fs";

const WALLET_FILE = process.env.TAPMARKET_WALLET ?? new URL("./wallet.json", import.meta.url).pathname;
if (!existsSync(WALLET_FILE)) {
  console.error("No wallet found. Run: npx tapmarket-connect setup");
  process.exit(1);
}
const wallet = JSON.parse(readFileSync(WALLET_FILE, "utf8"));

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

const server = new Server({ name: "tapmarket", version: "0.1.0" }, { capabilities: { tools: {} } });

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    { name: "list_specialists", description: "List hireable specialist agents on TapMarket with prices.", inputSchema: { type: "object", properties: {} } },
    { name: "hire_specialist", description: "Hire a specialist for one job. Pays the listed price from the connected wallet (spending is contract-limited to TapMarket only). Returns the work product, the charge, and the receipt.", inputSchema: { type: "object", properties: {
      specialist: { type: "string", description: "specialist id from list_specialists" },
      input: { type: "object", description: "hermes: {address: '0x..'}; scribe: {topic, keyword, links:[{name,url}]}" },
    }, required: ["specialist", "input"] } },
    { name: "get_balance", description: "Show wallet balance and spending limits.", inputSchema: { type: "object", properties: {} } },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  const { name, arguments: args } = req.params;
  try {
    if (name === "list_specialists") {
      const lines = CATALOG.map(s => `- ${s.id} (${s.pricePerUse}/use): ${s.description}`).join("\n");
      return { content: [{ type: "text", text: `${lines}\n\n${await balanceLine()}\n\n${LIMITS_TEXT}` }] };
    }
    if (name === "get_balance") {
      return { content: [{ type: "text", text: `${await balanceLine()}\n\n${LIMITS_TEXT}` }] };
    }
    if (name === "hire_specialist") {
      const spec = CATALOG.find(s => s.id === args.specialist);
      if (!spec) return { content: [{ type: "text", text: `Unknown specialist '${args.specialist}'. Use list_specialists.` }], isError: true };
      const route = { url: spec.endpoint, body: spec.shape };
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
      const res = await fetch(route.url, { method: "POST", headers: { "Content-Type": "application/json", "Authorization": `Bearer ${process.env.TAP_SERVICE_TOKEN ?? "public-testnet-v01"}` }, body: JSON.stringify(route.body(args.input, account.address)) });
      let out = await res.json();
      if (spec.async && out.job_id) {
        const deadline = Date.now() + 6 * 60 * 1000;
        while (Date.now() < deadline) {
          await new Promise(r => setTimeout(r, 10000));
          const pr = await fetch(spec.resultEndpoint + out.job_id, { headers: { "Authorization": `Bearer ${process.env.TAP_SERVICE_TOKEN ?? "public-testnet-v01"}` } });
          const pj = await pr.json();
          if (pj.status === "done") { out = pj; break; }
          if (pj.status === "failed") { return { content: [{ type: "text", text: `Job failed: ${pj.error}. If payment was taken, the pack remains usable — retry the hire.` }], isError: true }; }
        }
        if (out.job_id && !out.article) return { content: [{ type: "text", text: `Still working after 6 min. Job ${out.job_id} — retry hire_specialist in a few minutes; your prepaid pack will be used, not recharged.` }], isError: true };
      }
      try { appendFileSync(join(homedir(), ".tapmarket", "hires.jsonl"), JSON.stringify({ ts: new Date().toISOString(), specialist: spec.id, charge: spec.pricePerUse, payTx: payTxText, settleTx: out.settleTx }) + "\n"); } catch {}
      const work = out.assessment ?? out.article ?? out;
      return { content: [{ type: "text", text:
        `${chargedText}\n${await balanceLine()}\nPayment: ${payTxText}\nSettlement receipt: https://sepolia.basescan.org/tx/${out.settleTx}\n\nWORK PRODUCT:\n${JSON.stringify(work, null, 2)}` }] };
    }
    return { content: [{ type: "text", text: `Unknown tool ${name}` }], isError: true };
  } catch (e) {
    return { content: [{ type: "text", text: `Error: ${e.shortMessage ?? e.message}` }], isError: true };
  }
});

await server.connect(new StdioServerTransport());
console.error("tapmarket MCP server ready (stdio)");
