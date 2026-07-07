#!/usr/bin/env node
// owner-tools.js — owner-key operations on your TapMarket wallet.
// usage: node owner-tools.js refund   (reclaim unused escrow from all listings)
import { createPublicClient, http, parseAbi, encodeFunctionData, formatUnits } from "viem";
import { baseSepolia } from "viem/chains";
import { privateKeyToAccount } from "viem/accounts";
import { signerToEcdsaValidator } from "@zerodev/ecdsa-validator";
import { createKernelAccount, createKernelAccountClient } from "@zerodev/sdk";
import { KERNEL_V3_1, getEntryPoint } from "@zerodev/sdk/constants";
import { config } from "dotenv";
import { loadWallet, unlockOwnerKey, isOwnerKeyEncrypted } from "./wallet-store.js";

config({ path: new URL("../.env.local", import.meta.url).pathname, quiet: true });
const { wallet } = loadWallet();
if (!wallet) { console.error("No wallet found. Run: npx tapmarket-connect setup"); process.exit(1); }
if (isOwnerKeyEncrypted(wallet)) wallet.ownerKey = await unlockOwnerKey(wallet);

const TAP_MARKET = "0xBfd085f192d2246F1BFBe386DF399335dc894f2c";
const USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e";
const ZERODEV_RPC = `https://rpc.zerodev.app/api/v3/${process.env.ZERODEV_PROJECT_ID}/chain/84532`;
const abi = parseAbi([
  "function nextListingId() view returns (uint256)",
  "function refundUnused(uint256 listingId)",
  "function escrows(uint256,address) view returns (uint256 balance, uint256 usesPurchased, uint256 usesSettled, uint64 capPerPeriod, uint64 periodStart, uint64 usedThisPeriod, uint64 purchaseTime)",
]);
const usdcAbi = parseAbi(["function balanceOf(address) view returns (uint256)"]);

const publicClient = createPublicClient({ chain: baseSepolia, transport: http("https://sepolia.base.org") });
const entryPoint = getEntryPoint("0.7");
const owner = privateKeyToAccount(wallet.ownerKey);
const ecdsaValidator = await signerToEcdsaValidator(publicClient, { signer: owner, entryPoint, kernelVersion: KERNEL_V3_1 });
const account = await createKernelAccount(publicClient, { plugins: { sudo: ecdsaValidator }, entryPoint, kernelVersion: KERNEL_V3_1 });
if (account.address !== wallet.smartAccount) {
  console.error(`Owner key does not control ${wallet.smartAccount} (derived ${account.address})`); process.exit(1);
}
const kernelClient = createKernelAccountClient({ account, chain: baseSepolia, bundlerTransport: http(ZERODEV_RPC) });

const cmd = process.argv[2];
if (cmd !== "refund") { console.log("usage: node owner-tools.js refund"); process.exit(0); }

const n = await publicClient.readContract({ address: TAP_MARKET, abi, functionName: "nextListingId" });
const now = Math.floor(Date.now() / 1000);
const calls = [];
for (let i = 1n; i < n; i++) {
  const e = await publicClient.readContract({ address: TAP_MARKET, abi, functionName: "escrows", args: [i, account.address] });
  if (e[0] === 0n) continue;
  const unlockAt = Number(e[6]) + 86400;
  if (now < unlockAt) {
    console.log(`listing ${i}: $${formatUnits(e[0], 6)} locked until ${new Date(unlockAt * 1000).toLocaleString()} (1-day dispute window)`);
    continue;
  }
  console.log(`listing ${i}: refunding $${formatUnits(e[0], 6)}...`);
  calls.push({ to: TAP_MARKET, value: 0n, data: encodeFunctionData({ abi, functionName: "refundUnused", args: [i] }) });
}
if (!calls.length) { console.log("Nothing refundable right now."); process.exit(0); }

const hash = await kernelClient.sendUserOperation({ callData: await account.encodeCalls(calls) });
const receipt = await kernelClient.waitForUserOperationReceipt({ hash });
console.log("Refund tx:", receipt.receipt.transactionHash);
const bal = await publicClient.readContract({ address: USDC, abi: usdcAbi, functionName: "balanceOf", args: [account.address] });
console.log(`Wallet balance: $${formatUnits(bal, 6)} USDC`);
