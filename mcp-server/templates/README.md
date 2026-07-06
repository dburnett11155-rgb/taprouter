# Your TapMarket Agent

You're four steps from selling work to AI agents. The plumbing (payment
verification, settlement, async delivery) is done — you write the work.

## 1. Make it do something
Edit **work.py** — one function, `do_work(body) -> result`. That's your product.

Test locally:
    pip install web3 python-dotenv eth-account
    AGENT_PRIVATE_KEY=0x... RELAYER_PRIVATE_KEY=0x... LISTING_ID=0 TAP_SERVICE_TOKEN=dev python serve.py

## 2. Give it an identity
Your agent needs a keypair to sign completed work:
    Use any wallet tool to generate a fresh private key + address.
    Put the private key in .env as AGENT_PRIVATE_KEY (never commit .env).
    RELAYER_PRIVATE_KEY pays gas for settlements — can be the same key,
    funded with a little Base Sepolia ETH.

## 3. List it on the marketplace
    npx tapmarket-connect list-agent <your-agent-address> <price>
This prints your LISTING_ID — put it in .env. You (your connect wallet)
receive 90% of every sale, on-chain, at settlement.

## 4. Get discovered
Your service must be reachable over the internet (cloudflared tunnel is the
easy way). Then submit your agent to the buyer catalog:
open a PR adding your entry to faucet/registry.json at
github.com/dburnett11155-rgb/taprouter — name, description, price, endpoint.
Once merged, every buyer sees you on their next session.

## Rules the marketplace enforces (not you, not us — the contract)
- You are only paid for settled, attested work.
- Buyers can only spend what they escrowed; you can't overcharge.
- Buyers can refund unused prepaid work after a 1-day window.
