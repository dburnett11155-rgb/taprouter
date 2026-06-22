// chains.ts
// Deployed contract addresses + chain constants.
// Source of truth: TapRouter-Roadmap.md. Update here AND there together.

export type ChainKey = "arbitrumSepolia" | "baseSepolia";

export interface ChainConfig {
  chainId: number;
  rpcUrl: string;
  /** LayerZero v2 Endpoint ID */
  eid: number;
  /** Circle CCTP domain */
  cctpDomain: number;
  usdc: `0x${string}`;
  /** TapRouter — only deployed on the SENDING side of a given direction */
  router?: `0x${string}`;
  /** TapVault — only deployed on the RECEIVING side of a given direction */
  vault?: `0x${string}`;
}

// Arb Sepolia -> Base Sepolia is the ORIGINAL rail (router on Arb, vault on Base)
// Base Sepolia -> Arb Sepolia is the MIRROR rail (router on Base, vault on Arb)
// A given chain can host both a router (outbound) and a vault (inbound).

export const CHAINS: Record<ChainKey, ChainConfig> = {
  arbitrumSepolia: {
    chainId: 421614,
    rpcUrl: "https://sepolia-rollup.arbitrum.io/rpc",
    eid: 40231,
    cctpDomain: 3,
    usdc: "0x75faf114eafb1BDbe2F0316DF893fd58CE46AA4d",
    router: "0xf199414861A8F0D763C12670B4c3004A0e934d7F", // original rail, sends Arb->Base
    vault: "0x50F34ca85EAe9D1f9E25d4c57F700E98bD139721",  // mirror rail, receives Base->Arb
  },
  baseSepolia: {
    chainId: 84532,
    rpcUrl: "https://sepolia.base.org",
    eid: 40245,
    cctpDomain: 6,
    usdc: "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    router: "0xdd8d77182A184aDf5649cd3693a471c65dC53849", // mirror rail, sends Base->Arb
    vault: "0x1360d65342b1F9543ce2A69e07076efE75657025",  // original rail, receives Arb->Base
  },
};

export function routerFor(from: ChainKey): `0x${string}` {
  const cfg = CHAINS[from];
  if (!cfg.router) throw new Error(`No router deployed on ${from} as a source chain`);
  return cfg.router;
}

export function vaultFor(to: ChainKey): `0x${string}` {
  const cfg = CHAINS[to];
  if (!cfg.vault) throw new Error(`No vault deployed on ${to} as a destination chain`);
  return cfg.vault;
}
