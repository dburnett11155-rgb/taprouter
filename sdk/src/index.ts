// index.ts — public SDK surface
export { pay, waitForDelivery } from "./client";
export type { PayParams, PayResult, DeliveryStatus, WaitForDeliveryOptions } from "./client";
export { CHAINS, routerFor, vaultFor } from "./chains";
export type { ChainKey, ChainConfig } from "./chains";
