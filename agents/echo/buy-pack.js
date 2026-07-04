import { createPublicClient, http, parseAbi, encodeFunctionData } from "viem";
import { baseSepolia } from "viem/chains";
import { createKernelAccountClient } from "@zerodev/sdk";
import { KERNEL_V3_1, getEntryPoint } from "@zerodev/sdk/constants";
import { deserializePermissionAccount } from "@zerodev/permissions";
import { config } from "dotenv";

config({ path: "../../.env.local" });

const TAP_MARKET = "0xBfd085f192d2246F1BFBe386DF399335dc894f2c";
const ZERODEV_RPC = `https://rpc.zerodev.app/api/v3/${process.env.ZERODEV_PROJECT_ID}/chain/84532`;
const marketAbi = parseAbi([
  "function buyPack(uint256 listingId, uint256 numUses, uint64 capPerPeriod)",
  "function escrows(uint256,address) view returns (uint256 balance, uint256 usesPurchased, uint256 usesSettled, uint64 capPerPeriod, uint64 periodStart, uint64 usedThisPeriod, uint64 purchaseTime)",
]);

const publicClient = createPublicClient({ chain: baseSepolia, transport: http("https://sepolia.base.org") });
const entryPoint = getEntryPoint("0.7");

const account = await deserializePermissionAccount(
  publicClient, entryPoint, KERNEL_V3_1, process.env.SESSION_APPROVAL
);
console.log("Loaded session account:", account.address);

const kernelClient = createKernelAccountClient({
  account, chain: baseSepolia, bundlerTransport: http(ZERODEV_RPC),
});

console.log("Echo buying 1 use of Hermes (listing 1) via session key...");
const hash = await kernelClient.sendUserOperation({
  callData: await account.encodeCalls([{
    to: TAP_MARKET, value: 0n,
    data: encodeFunctionData({ abi: marketAbi, functionName: "buyPack", args: [1n, 1n, 10n] }),
  }]),
});
const receipt = await kernelClient.waitForUserOperationReceipt({ hash });
console.log("Tx hash:", receipt.receipt.transactionHash);

const pack = await publicClient.readContract({
  address: TAP_MARKET, abi: marketAbi, functionName: "escrows", args: [1n, account.address],
});
console.log("Pack state — escrow:", pack[0].toString(), "paidUses:", pack[1].toString(), "settledUses:", pack[2].toString());
console.log("ECHO BOUGHT A HERMES PACK AUTONOMOUSLY.");
