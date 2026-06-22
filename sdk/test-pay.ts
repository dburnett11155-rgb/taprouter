// test-pay.ts — live smoke test of the built SDK against the Arb->Base rail.
// Reads PRIVATE_KEY from env. Run: PRIVATE_KEY=$(grep PRIVATE_KEY ../.env.local | cut -d= -f2) npx tsx test-pay.ts
import { privateKeyToAccount } from "viem/accounts";
import { pay } from "./dist/index.mjs";

async function main() {
  const pk = process.env.PRIVATE_KEY;
  if (!pk) throw new Error("PRIVATE_KEY env var not set");
  const account = privateKeyToAccount(pk.startsWith("0x") ? pk as `0x${string}` : `0x${pk}`);

  console.log("Sender:", account.address);
  console.log("Firing 1.0 USDC  arbitrumSepolia -> baseSepolia ...");

  const result = await pay({
    account,
    from: "arbitrumSepolia",
    to: "baseSepolia",
    amount: 1.0,
    recipient: account.address, // send to self for the test
  });

  console.log("\n=== SUCCESS ===");
  console.log("swapId:      ", result.swapId);
  console.log("sourceTxHash:", result.sourceTxHash);
  console.log("\nArbiscan: https://sepolia.arbiscan.io/tx/" + result.sourceTxHash);
}

main().catch((e) => {
  console.error("\n=== FAILED ===");
  console.error(e);
  process.exit(1);
});
