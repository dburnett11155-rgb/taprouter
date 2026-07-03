import { createPublicClient, http, parseAbi } from "viem";
import { baseSepolia } from "viem/chains";
import { privateKeyToAccount, generatePrivateKey } from "viem/accounts";
import { signerToEcdsaValidator } from "@zerodev/ecdsa-validator";
import { createKernelAccount, createKernelAccountClient } from "@zerodev/sdk";
import { KERNEL_V3_1, getEntryPoint } from "@zerodev/sdk/constants";
import { toPermissionValidator } from "@zerodev/permissions";
import { toECDSASigner } from "@zerodev/permissions/signers";
import { toCallPolicy, CallPolicyVersion, ParamCondition } from "@zerodev/permissions/policies";
import { config } from "dotenv";

config({ path: "../../.env.local" });

const TAP_MARKET = "0xBfd085f192d2246F1BFBe386DF399335dc894f2c";
const USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e";
const ZERODEV_RPC = `https://rpc.zerodev.app/api/v3/${process.env.ZERODEV_PROJECT_ID}/chain/84532`;

const publicClient = createPublicClient({ chain: baseSepolia, transport: http("https://sepolia.base.org") });
const entryPoint = getEntryPoint("0.7");
const echoSigner = privateKeyToAccount(process.env.ECHO_PRIVATE_KEY);

// Owner validator (Echo's master key)
const ecdsaValidator = await signerToEcdsaValidator(publicClient, {
  signer: echoSigner, entryPoint, kernelVersion: KERNEL_V3_1,
});

// Session key: can ONLY call USDC.approve(TapMarket, ...) and TapMarket functions
const sessionPrivateKey = generatePrivateKey();
const sessionSigner = await toECDSASigner({ signer: privateKeyToAccount(sessionPrivateKey) });

const callPolicy = toCallPolicy({
  policyVersion: CallPolicyVersion.V0_0_4,
  permissions: [
    { target: USDC, abi: parseAbi(["function approve(address,uint256)"]), functionName: "approve", args: [{ condition: ParamCondition.EQUAL, value: TAP_MARKET }, null] },
    { target: TAP_MARKET, valueLimit: 0n },
  ],
});

const permissionPlugin = await toPermissionValidator(publicClient, {
  entryPoint, kernelVersion: KERNEL_V3_1,
  signer: sessionSigner,
  policies: [callPolicy],
});

const account = await createKernelAccount(publicClient, {
  plugins: { sudo: ecdsaValidator, regular: permissionPlugin },
  entryPoint, kernelVersion: KERNEL_V3_1,
});

console.log("Smart account:", account.address);

const kernelClient = createKernelAccountClient({
  account, chain: baseSepolia,
  bundlerTransport: http(ZERODEV_RPC),
});

// First scoped action: approve TapMarket to pull 1 USDC
const hash = await kernelClient.sendUserOperation({
  callData: await account.encodeCalls([{
    to: USDC, value: 0n,
    data: (await import("viem")).encodeFunctionData({
      abi: parseAbi(["function approve(address,uint256)"]),
      functionName: "approve",
      args: [TAP_MARKET, 1000000n],
    }),
  }]),
});
console.log("UserOp hash:", hash);
const receipt = await kernelClient.waitForUserOperationReceipt({ hash });
console.log("Tx hash:", receipt.receipt.transactionHash);
console.log("SESSION KEY WORKS — Echo approved TapMarket for 1 USDC, scoped.");
