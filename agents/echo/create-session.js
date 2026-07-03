import { createPublicClient, http, parseAbi } from "viem";
import { baseSepolia } from "viem/chains";
import { privateKeyToAccount, generatePrivateKey } from "viem/accounts";
import { signerToEcdsaValidator } from "@zerodev/ecdsa-validator";
import { createKernelAccount } from "@zerodev/sdk";
import { KERNEL_V3_1, getEntryPoint } from "@zerodev/sdk/constants";
import { toPermissionValidator, serializePermissionAccount } from "@zerodev/permissions";
import { toECDSASigner } from "@zerodev/permissions/signers";
import { toCallPolicy, CallPolicyVersion, ParamCondition } from "@zerodev/permissions/policies";
import { config } from "dotenv";
import { appendFileSync } from "fs";

config({ path: "../../.env.local" });

const TAP_MARKET = "0xBfd085f192d2246F1BFBe386DF399335dc894f2c";
const publicClient = createPublicClient({ chain: baseSepolia, transport: http("https://sepolia.base.org") });
const entryPoint = getEntryPoint("0.7");
const echoSigner = privateKeyToAccount(process.env.ECHO_PRIVATE_KEY);

const ecdsaValidator = await signerToEcdsaValidator(publicClient, {
  signer: echoSigner, entryPoint, kernelVersion: KERNEL_V3_1,
});

const sessionKey = generatePrivateKey();
const sessionSigner = await toECDSASigner({ signer: privateKeyToAccount(sessionKey) });

const callPolicy = toCallPolicy({
  policyVersion: CallPolicyVersion.V0_0_4,
  permissions: [
    { target: TAP_MARKET, abi: parseAbi(["function buyPack(uint256,uint256,uint64)"]), functionName: "buyPack" },
    { target: "0x036CbD53842c5426634e7929541eC2318f3dCF7e", abi: parseAbi(["function approve(address,uint256)"]), functionName: "approve", args: [{ condition: ParamCondition.EQUAL, value: TAP_MARKET }, null] },
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
appendFileSync("../../.env.local", `SESSION_APPROVAL=${approval}\n`);
console.log("Session approval created and saved for account:", account.address);
