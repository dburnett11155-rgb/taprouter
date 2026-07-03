// echo.js — Echo, the autonomous orchestrator. Task in → Qwen decides → pays → hires → result.
// usage: node echo.js "your task in plain english"
import { createPublicClient, http, parseAbi, encodeFunctionData } from "viem";
import { baseSepolia } from "viem/chains";
import { createKernelAccountClient } from "@zerodev/sdk";
import { KERNEL_V3_1, getEntryPoint } from "@zerodev/sdk/constants";
import { deserializePermissionAccount } from "@zerodev/permissions";
import { config } from "dotenv";
import { plan, CATALOG } from "./brain.js";

config({ path: "../../.env.local" });

const TAP_MARKET = "0xBfd085f192d2246F1BFBe386DF399335dc894f2c";
const ZERODEV_RPC = `https://rpc.zerodev.app/api/v3/${process.env.ZERODEV_PROJECT_ID}/chain/84532`;
const task = process.argv[2];
if (!task) { console.error('usage: node echo.js "task"'); process.exit(1); }

console.log("[echo] task:", task);
const decision = await plan(task);
console.log("[echo] decision:", decision.decision, "—", decision.reason);

if (decision.decision !== "hire") process.exit(0);
const spec = CATALOG.find(s => s.id === decision.specialist);
if (!spec) { console.error("[echo] planner picked unknown specialist:", decision.specialist); process.exit(1); }

const marketAbi = parseAbi(["function buyPack(uint256 listingId, uint256 numUses, uint64 capPerPeriod)"]);
const usdcAbi = parseAbi(["function approve(address,uint256)"]);
const USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e";
const publicClient = createPublicClient({ chain: baseSepolia, transport: http("https://sepolia.base.org") });
const account = await deserializePermissionAccount(
  publicClient, getEntryPoint("0.7"), KERNEL_V3_1, process.env.SESSION_APPROVAL
);
const kernelClient = createKernelAccountClient({ account, chain: baseSepolia, bundlerTransport: http(ZERODEV_RPC) });

console.log(`[echo] hiring ${spec.id} (${spec.pricePerUse}) via session key...`);
const hash = await kernelClient.sendUserOperation({
  callData: await account.encodeCalls([{
    to: USDC, value: 0n,
    data: encodeFunctionData({ abi: usdcAbi, functionName: "approve", args: [TAP_MARKET, 500000n] }),
  }, {
    to: TAP_MARKET, value: 0n,
    data: encodeFunctionData({ abi: marketAbi, functionName: "buyPack", args: [BigInt(spec.listingId), 1n, 1n] }),
  }]),
});
const receipt = await kernelClient.waitForUserOperationReceipt({ hash });
console.log("[echo] paid. tx:", receipt.receipt.transactionHash);

console.log("[echo] sending job (Qwen ~40s)...");
const res = await fetch("http://127.0.0.1:8787/assess", {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ address: decision.input, buyer: account.address }),
});
const out = await res.json();
console.log("[echo] specialist settled use", out.use, "tx:", out.settleTx);
console.log(JSON.stringify(out.assessment, null, 2));
