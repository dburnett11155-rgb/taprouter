#!/usr/bin/env node
// init.js — one-time setup: creates YOUR wallet for hiring TapMarket specialists.
// Keys are generated locally and never leave this machine.
import { createPublicClient, http, parseAbi } from "viem";
import { baseSepolia } from "viem/chains";
import { privateKeyToAccount, generatePrivateKey } from "viem/accounts";
import { signerToEcdsaValidator } from "@zerodev/ecdsa-validator";
import { createKernelAccount } from "@zerodev/sdk";
import { KERNEL_V3_1, getEntryPoint } from "@zerodev/sdk/constants";
import { toPermissionValidator, serializePermissionAccount } from "@zerodev/permissions";
import { toECDSASigner } from "@zerodev/permissions/signers";
import { toCallPolicy, CallPolicyVersion, ParamCondition } from "@zerodev/permissions/policies";
import { writeFileSync, existsSync } from "fs";

const WALLET_FILE = new URL("./wallet.json", import.meta.url).pathname;
if (existsSync(WALLET_FILE)) {
  console.error("wallet.json already exists — refusing to overwrite. Delete it manually to re-init.");
  process.exit(1);
}

const TAP_MARKET = "0xBfd085f192d2246F1BFBe386DF399335dc894f2c";
const USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e";

const publicClient = createPublicClient({ chain: baseSepolia, transport: http("https://sepolia.base.org") });
const entryPoint = getEntryPoint("0.7");

const ownerKey = generatePrivateKey();
const owner = privateKeyToAccount(ownerKey);

const ecdsaValidator = await signerToEcdsaValidator(publicClient, {
  signer: owner, entryPoint, kernelVersion: KERNEL_V3_1,
});

const sessionKey = generatePrivateKey();
const sessionSigner = await toECDSASigner({ signer: privateKeyToAccount(sessionKey) });
const callPolicy = toCallPolicy({
  policyVersion: CallPolicyVersion.V0_0_4,
  permissions: [
    { target: TAP_MARKET, abi: parseAbi(["function buyPack(uint256,uint256,uint64)"]), functionName: "buyPack" },
    { target: USDC, abi: parseAbi(["function approve(address,uint256)"]), functionName: "approve", args: [{ condition: ParamCondition.EQUAL, value: TAP_MARKET }, null] },
  ],
});
const permissionPlugin = await toPermissionValidator(publicClient, {
  entryPoint, kernelVersion: KERNEL_V3_1, signer: sessionSigner, policies: [callPolicy],
});

const account = await createKernelAccount(publicClient, {
  plugins: { sudo: ecdsaValidator, regular: permissionPlugin },
  entryPoint, kernelVersion: KERNEL_V3_1,
});
const approval = await serializePermissionAccount(account, sessionKey);

writeFileSync(WALLET_FILE, JSON.stringify({
  smartAccount: account.address,
  ownerKey,               // recovery + revocation key — keep safe
  sessionApproval: approval,
  created: new Date().toISOString(),
}, null, 2), { mode: 0o600 });

console.log(`
TapMarket wallet created.

  Your smart account: ${account.address}

WHAT THIS WALLET CAN DO (enforced by smart contract):
  - Buy specialist services on TapMarket. That's it.
  - It CANNOT send funds anywhere else, even if this machine is fully compromised.
  - You can revoke the spending key anytime with your owner key (stored in wallet.json).

NEXT STEP — fund it:
  Send Base Sepolia USDC to ${account.address}
  (testnet: free at https://faucet.circle.com, select Base Sepolia)
  Also send ~0.002 Base Sepolia ETH for gas.

wallet.json holds your keys. It never leaves this machine. Back it up.
`);
