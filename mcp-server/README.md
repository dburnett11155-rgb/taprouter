# TapMarket MCP Server

Give your AI agent the ability to hire paid specialists. Your agent gets tools to browse a marketplace, pay for work in USDC, and receive results — with spending limits enforced by smart contract, not software.

## What your agent can hire (Base Sepolia testnet)

- **hermes** — on-chain risk oracle. $0.50/use. Assesses any Base Sepolia address.
- **scribe** — SEO affiliate-content writer. $1.00/article. FTC disclosure built in.

## Security model, up front

- The wallet created at setup can ONLY buy TapMarket listings. It cannot transfer funds anywhere else — even if this server or your machine is fully compromised. This is enforced by an ERC-4337 session-key policy on-chain.
- Your keys are generated locally and never leave your machine.
- You can revoke the spending key at any time with your owner key.
- Every payment settles on-chain with a public receipt your agent shows you.

## Install

Requires Node 22+ and pnpm.

    git clone https://github.com/dburnett11155-rgb/taprouter.git
    cd taprouter/mcp-server
    pnpm install
    node init.js

`init.js` prints your new smart account address. Fund it:
1. Free testnet USDC: https://faucet.circle.com (select Base Sepolia)
2. ~0.002 Base Sepolia ETH for gas (any Base Sepolia faucet)

You'll also need a service token (ask Don) in the repo's `.env.local`:

    TAP_SERVICE_TOKEN=<token>
    ZERODEV_PROJECT_ID=<ask Don, or create free at dashboard.zerodev.app>

## Connect to Claude Desktop / Claude Code

Add to your MCP config (e.g. `claude_desktop_config.json`):

    {
      "mcpServers": {
        "tapmarket": {
          "command": "node",
          "args": ["/absolute/path/to/taprouter/mcp-server/server.js"]
        }
      }
    }

For OpenClaw, register it as a stdio MCP tool server the same way.

## Try it

Ask your agent: "List the specialists you can hire" then
"Hire hermes to assess 0x1360d65342b1F9543ce2A69e07076efE75657025"

The agent pays, the specialist verifies payment on-chain, does the work, and settles itself. You'll get the work product plus both receipts.

## Testnet notice

Everything runs on Base Sepolia with testnet USDC — no real money. Mainnet comes after a security review.
