import { createPublicClient, createWalletClient, http, parseAbi } from "viem";
import { baseSepolia } from "viem/chains";
import { privateKeyToAccount } from "viem/accounts";
import { config } from "dotenv";

config({ path: "../../.env.local" });

const TAP_MARKET = "0xBfd085f192d2246F1BFBe386DF399335dc894f2c";
const ECHO_SA = "0x3d91Bf0Bb312c94548D009A5CCFB1189042025AA";
const abi = parseAbi([
  "function settle(uint256 listingId, address buyer, uint256 cumulativeUses, uint256 expiry, bytes sig)",
  "function escrows(uint256,address) view returns (uint256 balance, uint256 usesPurchased, uint256 usesSettled, uint64 capPerPeriod, uint64 periodStart, uint64 usedThisPeriod, uint64 purchaseTime)",
]);

const publicClient = createPublicClient({ chain: baseSepolia, transport: http("https://sepolia.base.org") });
const hermes = privateKeyToAccount(process.env.HERMES_PRIVATE_KEY);
const deployer = privateKeyToAccount(process.env.PRIVATE_KEY);
const wallet = createWalletClient({ account: deployer, chain: baseSepolia, transport: http("https://sepolia.base.org") });

const expiry = BigInt(Math.floor(Date.now() / 1000) + 3600);
const sig = await hermes.signTypedData({
  domain: { name: "TapMarket", version: "1", chainId: 84532, verifyingContract: TAP_MARKET },
  types: { Attestation: [
    { name: "buyer", type: "address" },
    { name: "listingId", type: "uint256" },
    { name: "cumulativeUses", type: "uint256" },
    { name: "expiry", type: "uint256" },
  ]},
  primaryType: "Attestation",
  message: { buyer: ECHO_SA, listingId: 1n, cumulativeUses: 1n, expiry },
});
console.log("Hermes signed attestation for Echo's purchase.");

const hash = await wallet.writeContract({
  address: TAP_MARKET, abi, functionName: "settle",
  args: [1n, ECHO_SA, 1n, expiry, sig],
});
console.log("Settle tx:", hash);
await publicClient.waitForTransactionReceipt({ hash });

const e = await publicClient.readContract({ address: TAP_MARKET, abi, functionName: "escrows", args: [1n, ECHO_SA] });
console.log("After settle — balance:", e[0].toString(), "settledUses:", e[2].toString());
console.log("FULL LOOP CLOSED: Echo paid autonomously, Hermes attested, money moved.");
