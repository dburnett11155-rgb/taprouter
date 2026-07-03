import { createPublicClient, http, parseAbi, encodeFunctionData } from "viem";
import { baseSepolia } from "viem/chains";
import { createKernelAccountClient } from "@zerodev/sdk";
import { KERNEL_V3_1, getEntryPoint } from "@zerodev/sdk/constants";
import { deserializePermissionAccount } from "@zerodev/permissions";
import { config } from "dotenv";

config({ path: "../../.env.local" });

const TAP_MARKET = "0xBfd085f192d2246F1BFBe386DF399335dc894f2c";
const ZERODEV_RPC = `https://rpc.zerodev.app/api/v3/${process.env.ZERODEV_PROJECT_ID}/chain/84532`;
const TARGET = process.argv[2];
if (!TARGET) { console.error("usage: node orchestrate.js <address-to-assess>"); process.exit(1); }

const marketAbi = parseAbi(["function buyPack(uint256 listingId, uint256 numUses, uint64 capPerPeriod)"]);
const publicClient = createPublicClient({ chain: baseSepolia, transport: http("https://sepolia.base.org") });

const account = await deserializePermissionAccount(
  publicClient, getEntryPoint("0.7"), KERNEL_V3_1, process.env.SESSION_APPROVAL
);
const kernelClient = createKernelAccountClient({ account, chain: baseSepolia, bundlerTransport: http(ZERODEV_RPC) });

console.log("[echo] task: risk-assess", TARGET);
console.log("[echo] buying 1 Hermes use via session key...");
const hash = await kernelClient.sendUserOperation({
  callData: await account.encodeCalls([{
    to: TAP_MARKET, value: 0n,
    data: encodeFunctionData({ abi: marketAbi, functionName: "buyPack", args: [1n, 1n, 1n] }),
  }]),
});
const receipt = await kernelClient.waitForUserOperationReceipt({ hash });
console.log("[echo] paid. tx:", receipt.receipt.transactionHash);

console.log("[echo] sending job to Hermes (Qwen runs ~40s on Pi)...");
const res = await fetch("http://127.0.0.1:8787/assess", {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ address: TARGET, buyer: account.address }),
});
const out = await res.json();
console.log("[echo] Hermes settled use", out.use, "tx:", out.settleTx);
console.log("[echo] assessment received:");
console.log(JSON.stringify(out.assessment, null, 2));
