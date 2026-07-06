// init-lib.js — creates a TapMarket-scoped smart account. Keys never leave this machine.
import { createPublicClient, http, parseAbi } from "viem";
import { baseSepolia } from "viem/chains";
import { privateKeyToAccount, generatePrivateKey } from "viem/accounts";
import { signerToEcdsaValidator } from "@zerodev/ecdsa-validator";
import { createKernelAccount } from "@zerodev/sdk";
import { KERNEL_V3_1, getEntryPoint } from "@zerodev/sdk/constants";
import { toPermissionValidator, serializePermissionAccount } from "@zerodev/permissions";
import { toECDSASigner } from "@zerodev/permissions/signers";
import { toCallPolicy, CallPolicyVersion, ParamCondition } from "@zerodev/permissions/policies";

export const TAP_MARKET = "0xBfd085f192d2246F1BFBe386DF399335dc894f2c";
export const USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e";
export const ZERODEV_PROJECT_ID = process.env.ZERODEV_PROJECT_ID ?? "c177e1e1-4df7-43fa-b9a6-be7ad4a6315f";
export const ZERODEV_RPC = `https://rpc.zerodev.app/api/v3/${ZERODEV_PROJECT_ID}/chain/84532`;

export async function createWallet() {
  const publicClient = createPublicClient({ chain: baseSepolia, transport: http("https://sepolia.base.org") });
  const entryPoint = getEntryPoint("0.7");
  const ownerKey = generatePrivateKey();
  const owner = privateKeyToAccount(ownerKey);
  const ecdsaValidator = await signerToEcdsaValidator(publicClient, { signer: owner, entryPoint, kernelVersion: KERNEL_V3_1 });
  const sessionKey = generatePrivateKey();
  const sessionSigner = await toECDSASigner({ signer: privateKeyToAccount(sessionKey) });
  const callPolicy = toCallPolicy({
    policyVersion: CallPolicyVersion.V0_0_4,
    permissions: [
      { target: TAP_MARKET, abi: parseAbi(["function buyPack(uint256,uint256,uint64)"]), functionName: "buyPack" },
      { target: TAP_MARKET, abi: parseAbi(["function refundUnused(uint256)"]), functionName: "refundUnused" },
      { target: USDC, abi: parseAbi(["function approve(address,uint256)"]), functionName: "approve", args: [{ condition: ParamCondition.EQUAL, value: TAP_MARKET }, null] },
    ],
  });
  const permissionPlugin = await toPermissionValidator(publicClient, { entryPoint, kernelVersion: KERNEL_V3_1, signer: sessionSigner, policies: [callPolicy] });
  const account = await createKernelAccount(publicClient, {
    plugins: { sudo: ecdsaValidator, regular: permissionPlugin },
    entryPoint, kernelVersion: KERNEL_V3_1,
  });
  const sessionApproval = await serializePermissionAccount(account, sessionKey);
  return { smartAccount: account.address, ownerKey, sessionApproval, created: new Date().toISOString() };
}

export async function revokeSessionKey(wallet) {
  const { createKernelAccountClient } = await import("@zerodev/sdk");
  const { deserializePermissionAccount } = await import("@zerodev/permissions");
  const publicClient = createPublicClient({ chain: baseSepolia, transport: http("https://sepolia.base.org") });
  const entryPoint = getEntryPoint("0.7");
  const owner = privateKeyToAccount(wallet.ownerKey);
  const ecdsaValidator = await signerToEcdsaValidator(publicClient, { signer: owner, entryPoint, kernelVersion: KERNEL_V3_1 });
  // Rebuild the permission plugin from the stored approval, then uninstall it via the sudo validator
  const { deserializePermissionAccount: deser } = await import("@zerodev/permissions");
  const sessionAccount = await deser(publicClient, entryPoint, KERNEL_V3_1, wallet.sessionApproval);
  const regularPlugin = sessionAccount.kernelPluginManager.getValidator?.() ?? sessionAccount.kernelPluginManager;
  const sudoAccount = await createKernelAccount(publicClient, {
    plugins: { sudo: ecdsaValidator },
    entryPoint, kernelVersion: KERNEL_V3_1, address: wallet.smartAccount,
  });
  const client = createKernelAccountClient({ account: sudoAccount, chain: baseSepolia, bundlerTransport: http(ZERODEV_RPC) });
  const code = await publicClient.getCode({ address: wallet.smartAccount });
  let hash;
  if (!code || code === "0x") {
    // Account never deployed: the session key was never installed on-chain.
    // Kill switch = deploy + invalidate the enable-nonce so the stored approval can never activate.
    const { getKernelV3Nonce } = await import("@zerodev/sdk");
    const nonce = await getKernelV3Nonce(publicClient, wallet.smartAccount).catch(() => 1);
    hash = await client.invalidateNonce({ nonceToSet: Number(nonce) + 1 });
  } else {
    hash = await client.uninstallPlugin({ plugin: regularPlugin });
  }
  const receipt = await client.waitForUserOperationReceipt({ hash });
  return receipt.receipt.transactionHash;
}

export async function withdraw(wallet, toAddress, amountUnits) {
  const { createKernelAccountClient } = await import("@zerodev/sdk");
  const { encodeFunctionData } = await import("viem");
  const publicClient = createPublicClient({ chain: baseSepolia, transport: http("https://sepolia.base.org") });
  const entryPoint = getEntryPoint("0.7");
  const owner = privateKeyToAccount(wallet.ownerKey);
  const ecdsaValidator = await signerToEcdsaValidator(publicClient, { signer: owner, entryPoint, kernelVersion: KERNEL_V3_1 });
  const account = await createKernelAccount(publicClient, {
    plugins: { sudo: ecdsaValidator },
    entryPoint, kernelVersion: KERNEL_V3_1, address: wallet.smartAccount,
  });
  const client = createKernelAccountClient({ account, chain: baseSepolia, bundlerTransport: http(ZERODEV_RPC) });
  const usdcAbi = parseAbi(["function transfer(address,uint256) returns (bool)"]);
  const hash = await client.sendUserOperation({
    callData: await account.encodeCalls([
      { to: USDC, value: 0n, data: encodeFunctionData({ abi: usdcAbi, functionName: "transfer", args: [toAddress, BigInt(amountUnits)] }) },
    ]),
  });
  const receipt = await client.waitForUserOperationReceipt({ hash });
  return receipt.receipt.transactionHash;
}

export async function listAgent(wallet, agentSigner, priceUnits) {
  const { createKernelAccountClient } = await import("@zerodev/sdk");
  const { encodeFunctionData } = await import("viem");
  const publicClient = createPublicClient({ chain: baseSepolia, transport: http("https://sepolia.base.org") });
  const entryPoint = getEntryPoint("0.7");
  const owner = privateKeyToAccount(wallet.ownerKey);
  const ecdsaValidator = await signerToEcdsaValidator(publicClient, { signer: owner, entryPoint, kernelVersion: KERNEL_V3_1 });
  const account = await createKernelAccount(publicClient, {
    plugins: { sudo: ecdsaValidator },
    entryPoint, kernelVersion: KERNEL_V3_1, address: wallet.smartAccount,
  });
  const client = createKernelAccountClient({ account, chain: baseSepolia, bundlerTransport: http(ZERODEV_RPC) });
  const marketAbi = parseAbi([
    "function listAgent(address agentSigner, uint256 pricePerUse, uint32 payoutChainEid) returns (uint256)",
    "function nextListingId() view returns (uint256)",
  ]);
  const expectedId = await publicClient.readContract({ address: TAP_MARKET, abi: marketAbi, functionName: "nextListingId" });
  const hash = await client.sendUserOperation({
    callData: await account.encodeCalls([
      { to: TAP_MARKET, value: 0n, data: encodeFunctionData({ abi: marketAbi, functionName: "listAgent", args: [agentSigner, BigInt(priceUnits), 0] }) },
    ]),
  });
  const receipt = await client.waitForUserOperationReceipt({ hash });
  return { listingId: expectedId, tx: receipt.receipt.transactionHash };
}
