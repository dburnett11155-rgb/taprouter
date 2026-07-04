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
import { CATALOG } from "../agents/echo/brain.js";

config({ path: new URL("../.env.local", import.meta.url).pathname, quiet: true });

const TAP_MARKET = "0xBfd085f192d2246F1BFBe386DF399335dc894f2c";
const USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e";
const ZERODEV_RPC = `https://rpc.zerodev.app/api/v3/${process.env.ZERODEV_PROJECT_ID}/chain/84532`;
const ROUTES = {
  hermes: { url: "https://hermes.tappayment.io/assess", body: (input, buyer) => ({ address: input.address, buyer }) },
  scribe: { url: "https://scribe.tappayment.io/write", body: (input, buyer) => ({ ...input, buyer }) },
};

const marketAbi = parseAbi(["function buyPack(uint256 listingId, uint256 numUses, uint64 capPerPeriod)"]);
const usdcAbi = parseAbi(["function approve(address,uint256)", "function balanceOf(address) view returns (uint256)"]);
const publicClient = createPublicClient({ chain: baseSepolia, transport: http("https://sepolia.base.org") });
const account = await deserializePermissionAccount(
  publicClient, getEntryPoint("0.7"), KERNEL_V3_1, process.env.SESSION_APPROVAL
);
const kernelClient = createKernelAccountClient({ account, chain: baseSepolia, bundlerTransport: http(ZERODEV_RPC) });

const LIMITS_TEXT = `Spending limits (enforced by smart contract, not by this software):
- This wallet can ONLY spend on TapMarket listings and approve USDC to TapMarket. No other transfers are possible, even if this server is compromised.
- Revoke anytime: the account owner can disable the session key with one transaction, instantly freezing all spending.
- Every payment settles on-chain with a public receipt.`;

async function balanceLine() {
  const bal = await publicClient.readContract({ address: USDC, abi: usdcAbi, functionName: "balanceOf", args: [account.address] });
  return `Wallet balance: $${formatUnits(bal, 6)} USDC`;
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
      const route = ROUTES[spec.id];
      const hash = await kernelClient.sendUserOperation({
        callData: await account.encodeCalls([
          { to: USDC, value: 0n, data: encodeFunctionData({ abi: usdcAbi, functionName: "approve", args: [TAP_MARKET, BigInt(spec.priceUnits)] }) },
          { to: TAP_MARKET, value: 0n, data: encodeFunctionData({ abi: marketAbi, functionName: "buyPack", args: [BigInt(spec.listingId), 1n, 1n] }) },
        ]),
      });
      const receipt = await kernelClient.waitForUserOperationReceipt({ hash });
      const res = await fetch(route.url, { method: "POST", headers: { "Content-Type": "application/json", "Authorization": `Bearer ${process.env.TAP_SERVICE_TOKEN}` }, body: JSON.stringify(route.body(args.input, account.address)) });
      const out = await res.json();
      appendFileSync(new URL("./hires.jsonl", import.meta.url).pathname, JSON.stringify({ ts: new Date().toISOString(), specialist: spec.id, charge: spec.pricePerUse, payTx: receipt.receipt.transactionHash, settleTx: out.settleTx }) + "\n");
      const work = out.assessment ?? out.article ?? out;
      return { content: [{ type: "text", text:
        `CHARGED: ${spec.pricePerUse} to ${spec.id}\n${await balanceLine()}\nPayment receipt: https://sepolia.basescan.org/tx/${receipt.receipt.transactionHash}\nSettlement receipt: https://sepolia.basescan.org/tx/${out.settleTx}\n\nWORK PRODUCT:\n${JSON.stringify(work, null, 2)}` }] };
    }
    return { content: [{ type: "text", text: `Unknown tool ${name}` }], isError: true };
  } catch (e) {
    return { content: [{ type: "text", text: `Error: ${e.shortMessage ?? e.message}` }], isError: true };
  }
});

await server.connect(new StdioServerTransport());
console.error("tapmarket MCP server ready (stdio)");
