// catalog.js — the TapMarket specialist registry (static v1; becomes a live registry in Phase 3)
export const CATALOG = [
  {
    id: "hermes",
    listingId: 1,
    pricePerUse: "0.15 USDC",
    priceUnits: 150000,
    description: "On-chain risk oracle for BASE SEPOLIA ONLY. Assesses any EVM address on Base Sepolia and returns a structured risk report. Cannot check other chains like Arbitrum or mainnet.",
    input: "an 0x EVM address",
    endpoint: "https://hermes.tappayment.io/assess",
    shape: (input, buyer) => ({ address: input.address, buyer }),
  },
  {
    id: "scribe",
    listingId: 2,
    pricePerUse: "0.25 USDC",
    priceUnits: 250000,
    description: "SEO affiliate-content writer. Writes a 500-700 word article on a topic, embedding the buyer's affiliate links, with FTC disclosure. Needs: topic, target keyword, affiliate link(s).",
    input: "topic + keyword + affiliate links",
    endpoint: "https://scribe.tappayment.io/write",
    async: true,
    resultEndpoint: "https://scribe.tappayment.io/result/",
    shape: (input, buyer) => ({ ...input, buyer }),
  },
];
