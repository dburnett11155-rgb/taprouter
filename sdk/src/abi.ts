// abi.ts
// Minimal ABI fragments — only what the SDK calls.
// Full ABIs live in contracts/out/ after `forge build`; pull from there if more is needed.

export const ROUTER_ABI = [
  {
    type: "function",
    name: "initiateSwap",
    stateMutability: "payable",
    inputs: [
      { name: "amount", type: "uint256" },
      { name: "recipient", type: "address" },
    ],
    outputs: [],
  },
  {
    type: "function",
    name: "quoteSwapFee",
    stateMutability: "view",
    inputs: [
      { name: "amount", type: "uint256" },
      { name: "recipient", type: "address" },
    ],
    outputs: [{ name: "fee", type: "uint256" }],
  },
  {
    // Verified against deployed TapRouter.sol (contracts/src/TapRouter.sol:34)
    type: "event",
    name: "SwapInitiated",
    inputs: [
      { name: "swapId", type: "bytes32", indexed: true },
      { name: "sender", type: "address", indexed: true },
      { name: "recipient", type: "address", indexed: true },
      { name: "amount", type: "uint256", indexed: false },
    ],
  },
] as const;

export const VAULT_ABI = [
  {
    type: "function",
    name: "outstandingFronted",
    stateMutability: "view",
    inputs: [],
    outputs: [{ name: "", type: "uint256" }],
  },
  {
    // Verified against deployed TapVault.sol (contracts/src/TapVault.sol:46)
    type: "event",
    name: "SwapExecuted",
    inputs: [
      { name: "swapId", type: "bytes32", indexed: true },
      { name: "recipient", type: "address", indexed: true },
      { name: "amountIn", type: "uint256", indexed: false },
      { name: "payout", type: "uint256", indexed: false },
      { name: "fronted", type: "bool", indexed: false },
    ],
  },
  {
    // Verified against deployed TapVault.sol (contracts/src/TapVault.sol:48)
    type: "event",
    name: "Reconciled",
    inputs: [
      { name: "cleared", type: "uint256", indexed: false },
      { name: "outstandingRemaining", type: "uint256", indexed: false },
    ],
  },
] as const;

export const USDC_ABI = [
  {
    type: "function",
    name: "approve",
    stateMutability: "nonpayable",
    inputs: [
      { name: "spender", type: "address" },
      { name: "amount", type: "uint256" },
    ],
    outputs: [{ name: "", type: "bool" }],
  },
  {
    type: "function",
    name: "allowance",
    stateMutability: "view",
    inputs: [
      { name: "owner", type: "address" },
      { name: "spender", type: "address" },
    ],
    outputs: [{ name: "", type: "uint256" }],
  },
  {
    type: "function",
    name: "balanceOf",
    stateMutability: "view",
    inputs: [{ name: "account", type: "address" }],
    outputs: [{ name: "", type: "uint256" }],
  },
] as const;
