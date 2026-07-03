import { createPublicClient, http } from "viem";
import { baseSepolia } from "viem/chains";
import { privateKeyToAccount } from "viem/accounts";
import { signerToEcdsaValidator } from "@zerodev/ecdsa-validator";
import { createKernelAccount } from "@zerodev/sdk";
import { KERNEL_V3_1, getEntryPoint } from "@zerodev/sdk/constants";
import { config } from "dotenv";

config({ path: "../../.env.local" });

const publicClient = createPublicClient({
  chain: baseSepolia,
  transport: http("https://sepolia.base.org"),
});

const echoSigner = privateKeyToAccount(process.env.ECHO_PRIVATE_KEY);
const entryPoint = getEntryPoint("0.7");

const ecdsaValidator = await signerToEcdsaValidator(publicClient, {
  signer: echoSigner,
  entryPoint,
  kernelVersion: KERNEL_V3_1,
});

const account = await createKernelAccount(publicClient, {
  plugins: { sudo: ecdsaValidator },
  entryPoint,
  kernelVersion: KERNEL_V3_1,
});

console.log("Echo signer (EOA):", echoSigner.address);
console.log("Echo smart account:", account.address);
