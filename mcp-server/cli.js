#!/usr/bin/env node
// tapmarket-connect — one-command setup for giving your AI assistant hiring power.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "fs";
import { homedir, platform } from "os";
import { join } from "path";
import { fileURLToPath } from "url";

const HOME_DIR = join(homedir(), ".tapmarket");
const WALLET = process.env.TAPMARKET_WALLET ?? join(HOME_DIR, "wallet.json");
const cmd = process.argv[2];

if (cmd === "setup") {
  const { createWallet } = await import("./init-lib.js");
  mkdirSync(HOME_DIR, { recursive: true });
  if (existsSync(WALLET)) {
    console.log(`Wallet already exists at ${WALLET} — skipping creation.`);
  } else {
    const w = await createWallet();
    writeFileSync(WALLET, JSON.stringify(w, null, 2), { mode: 0o600 });
    console.log(`
Your assistant's wallet is ready.

  Address: ${w.smartAccount}

WHAT IT CAN DO (enforced by the blockchain, not this software):
  - Buy specialist services on TapMarket. Nothing else.
  - It cannot send funds anywhere else, even if your machine is compromised.
  - You can freeze it anytime: npx tapmarket-connect revoke

`);
    process.stdout.write("Adding free test money... ");
    try {
      const r = await fetch("https://fund.tappayment.io/fund", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address: w.smartAccount }),
      });
      const j = await r.json();
      if (j.funded) console.log(`done! $${j.usdc} USDC is in your wallet.`);
      else throw new Error(j.error);
    } catch (e) {
      console.log(`didn't work (${e.message}).`);
      console.log(`Get free test money manually: https://faucet.circle.com (Base Sepolia) -> ${w.smartAccount}`);
    }
  }
  // Claude Desktop config injection
  const cfgPath = platform() === "darwin"
    ? join(homedir(), "Library", "Application Support", "Claude", "claude_desktop_config.json")
    : platform() === "win32"
    ? join(process.env.APPDATA ?? "", "Claude", "claude_desktop_config.json")
    : join(homedir(), ".config", "Claude", "claude_desktop_config.json");
  try {
    const cfg = existsSync(cfgPath) ? JSON.parse(readFileSync(cfgPath, "utf8")) : {};
    cfg.mcpServers = cfg.mcpServers ?? {};
    cfg.mcpServers.tapmarket = { command: "npx", args: ["-y", "tapmarket-connect@latest", "serve"] };
    mkdirSync(join(cfgPath, ".."), { recursive: true });
    writeFileSync(cfgPath, JSON.stringify(cfg, null, 2));
    try {
    const { launchDashboard } = await import("./dashboard.js");
    launchDashboard(WALLET);
    console.log("Your wallet dashboard is opening in the browser (Ctrl+C when done).");
  } catch {}
  console.log(`Claude Desktop connected (${cfgPath}). Restart Claude Desktop to activate.`);
  } catch (e) {
    console.log(`Couldn't auto-configure Claude Desktop (${e.message}).`);
    console.log(`Add manually to your MCP config:\n  "tapmarket": { "command": "npx", "args": ["-y", "tapmarket-connect@latest", "serve"] }`);
  }
  process.exit(0);
}

if (cmd === "serve") {
  process.env.TAPMARKET_WALLET = WALLET;
  await import("./server.js");
} else if (cmd === "refund") {
  process.env.TAPMARKET_WALLET = WALLET;
  process.argv[2] = "refund";
  await import("./owner-tools.js");
} else if (cmd === "dashboard") {
  const { launchDashboard } = await import("./dashboard.js");
  launchDashboard(WALLET);
  console.log("Press Ctrl+C to close.");
} else if (cmd === "withdraw") {
  const [, , , amount, to] = process.argv;
  if (!amount || !to?.startsWith("0x")) {
    console.log("usage: npx tapmarket-connect withdraw <amount-usdc> <0x-address>"); process.exit(1);
  }
  const { withdraw } = await import("./init-lib.js");
  const w = JSON.parse(readFileSync(WALLET, "utf8"));
  const units = Math.round(parseFloat(amount) * 1e6);
  console.log(`Withdrawing $${amount} USDC from ${w.smartAccount} to ${to}...`);
  const tx = await withdraw(w, to, units);
  console.log(`Done. Tx: https://sepolia.basescan.org/tx/${tx}`);
} else if (cmd === "revoke") {
  process.env.TAPMARKET_WALLET = WALLET;
  const { revokeSessionKey } = await import("./init-lib.js");
  const w = JSON.parse(readFileSync(WALLET, "utf8"));
  console.log("Freezing your assistant's spending key (this is reversible only by creating a new one)...");
  const tx = await revokeSessionKey(w);
  console.log(`Done. Spending frozen. Tx: https://sepolia.basescan.org/tx/${tx}`);
} else {
  console.log(`tapmarket-connect — give your AI assistant hiring power

  npx tapmarket-connect setup    create your assistant's wallet + connect Claude Desktop
  npx tapmarket-connect serve    run the connector (Claude launches this automatically)
  npx tapmarket-connect refund   reclaim unused prepaid tasks
`);
}
