import { waitForDelivery } from "./dist/index.mjs";

const swapId = "0x87fd26924c92d823626c2b775b726956a65f74f7fe28f11674885cf51dce4dce";

async function main() {
  console.log("Waiting for delivery of", swapId, "on baseSepolia ...");
  const status = await waitForDelivery(swapId as `0x${string}`, {
    chain: "baseSepolia",
    pollIntervalMs: 10000,
  });
  console.log("\n=== DELIVERED ===");
  console.log("delivered: ", status.delivered);
  console.log("fronted:   ", status.fronted);
  console.log("reconciled:", status.reconciled);
}
main().catch((e) => { console.error("FAILED:", e); process.exit(1); });
