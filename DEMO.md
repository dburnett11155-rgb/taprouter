# TapMarket: Autonomous Agent-to-Agent Commerce — Live Demo

Two AI agents doing business with each other. Real money, real work, no human in the loop.

## What happens when you run one command

    node agents/echo/echo.js "Is the token at 0x... safe to interact with?"

1. **Echo** (orchestrator, local Qwen 2.5 brain) reads the task and decides whether any listed specialist fits. If none does, it refuses and spends nothing.
2. If it hires: Echo pays **0.5 USDC** on TapMarket through an ERC-4337 smart account whose **session key is contract-limited** — it can only call `buyPack` on TapMarket and `approve` USDC to TapMarket. Even fully compromised, it cannot drain funds or pay anyone else.
3. **Hermes** (specialist, on-chain risk oracle, local Qwen) verifies on-chain that it was paid before working.
4. Hermes runs a real risk assessment, signs an EIP-712 attestation of the completed use, and settles itself: **90% to the builder, 10% protocol fee.**
5. Echo receives a structured risk report.

Everything runs on a Raspberry Pi 5. Inference cost: $0 (local models).

## On-chain receipts (Base Sepolia)

- Echo autonomously buys a use-pack: https://sepolia.basescan.org/tx/0xf02431e77086650febd9c1eb8e28d1a1ff0df71caf4bbe0252109b414d139c5f
- Hermes attests + settles, fee splits: https://sepolia.basescan.org/tx/0x96ee402fa58ff559fc689644386729aa18b8b18b405401920c50f988da13cdf7
- TapMarket contract (Sourcify-verified): https://sepolia.basescan.org/address/0xBfd085f192d2246F1BFBe386DF399335dc894f2c

## Why this is different

Agent marketplaces exist. Agent runtimes exist. What doesn't exist elsewhere: **agents autonomously paying agents with contract-enforced spending limits**, settled through a marketplace that takes a protocol fee, on rails that also settle cross-chain (TapRouter: LayerZero v2 + CCTP with LP-fronting, ~4 min delivery).

The buyer being an AI agent instead of a human required zero changes to the marketplace contract. Any agent can be a customer.

## Stack

Solidity (Foundry) · ERC-4337 session keys (ZeroDev Kernel) · viem · Ollama + Qwen 2.5 3B · Go settlement daemon · Raspberry Pi 5
