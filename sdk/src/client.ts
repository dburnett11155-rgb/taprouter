// client.ts
import {
  createPublicClient,
  createWalletClient,
  http,
  parseAbiItem,
  type Account,
  type Hash,
  type PublicClient,
  type WalletClient,
} from "viem";
import { CHAINS, routerFor, vaultFor, type ChainKey } from "./chains";
import { ROUTER_ABI, USDC_ABI, VAULT_ABI } from "./abi";

export interface PayParams {
  /** A viem Account (e.g. from privateKeyToAccount, or any signer-backed account) */
  account: Account;
  from: ChainKey;
  to: ChainKey;
  /** Amount in whole USDC, e.g. 1.5 for $1.50. Internally converted to 6-decimal units. */
  amount: number;
  recipient: `0x${string}`;
}

export interface PayResult {
  /** The on-chain swap identifier emitted by SwapInitiated — use with waitForDelivery() */
  swapId: Hash;
  /** The source-chain transaction hash (CCTP burn + LZ send) */
  sourceTxHash: Hash;
}

export interface DeliveryStatus {
  delivered: boolean;
  /** True if the recipient was paid from LP liquidity before the CCTP mint landed */
  fronted: boolean;
  /** True once reconcile() has cleared any fronted debt against the real CCTP mint */
  reconciled: boolean;
}

const USDC_DECIMALS = 6;

function toUnits(amount: number): bigint {
  return BigInt(Math.round(amount * 10 ** USDC_DECIMALS));
}

function publicClientFor(chain: ChainKey): PublicClient {
  const cfg = CHAINS[chain];
  return createPublicClient({ transport: http(cfg.rpcUrl) }) as PublicClient;
}

function walletClientFor(chain: ChainKey, account: Account): WalletClient {
  const cfg = CHAINS[chain];
  return createWalletClient({ account, transport: http(cfg.rpcUrl) });
}

/**
 * pay() — initiate a cross-chain USDC payment via TapRouter.
 *
 * Resolves as soon as the source-chain transaction (CCTP burn + LZ send) confirms.
 * Does NOT wait for destination delivery — call waitForDelivery(swapId) for that.
 *
 * Handles USDC approval automatically if the router's current allowance is insufficient.
 */
export async function pay(params: PayParams): Promise<PayResult> {
  const { account, from, to, amount, recipient } = params;

  if (from === to) {
    throw new Error(
      `pay(): same-chain transfers (${from} -> ${to}) are not supported by TapRouter. ` +
        `Same-chain agent-to-agent payments are explicitly deferred — see roadmap §4. ` +
        `Use a direct ERC-20 transfer instead.`
    );
  }

  const sourceCfg = CHAINS[from];
  const router = routerFor(from);
  const amountUnits = toUnits(amount);

  const publicClient = publicClientFor(from);
  const walletClient = walletClientFor(from, account);

  const currentAllowance = await publicClient.readContract({
    address: sourceCfg.usdc,
    abi: USDC_ABI,
    functionName: "allowance",
    args: [account.address, router],
  });

  if (currentAllowance < amountUnits) {
    const approveHash = await walletClient.writeContract({
      address: sourceCfg.usdc,
      abi: USDC_ABI,
      functionName: "approve",
      args: [router, amountUnits],
      chain: null,
      account,
    });
    await publicClient.waitForTransactionReceipt({ hash: approveHash });
  }

  const fee = await publicClient.readContract({
    address: router,
    abi: ROUTER_ABI,
    functionName: "quoteSwapFee",
    args: [amountUnits, recipient],
  });

  const sourceTxHash = await walletClient.writeContract({
    address: router,
    abi: ROUTER_ABI,
    functionName: "initiateSwap",
    args: [amountUnits, recipient],
    value: fee,
    chain: null,
    account,
  });

  const receipt = await publicClient.waitForTransactionReceipt({ hash: sourceTxHash });

  const log = receipt.logs.find((l) => {
    try {
      return l.address.toLowerCase() === router.toLowerCase();
    } catch {
      return false;
    }
  });

  if (!log || !log.topics[1]) {
    throw new Error(
      "pay(): source transaction confirmed but no SwapInitiated event found. " +
        "Check the transaction manually: " + sourceTxHash
    );
  }

  return {
    swapId: log.topics[1] as Hash,
    sourceTxHash,
  };
}

export interface WaitForDeliveryOptions {
  /** Destination chain to watch — must match the `to` used in pay() */
  chain: ChainKey;
  /** Polling interval in ms. Default 5000. */
  pollIntervalMs?: number;
  /** Max time to wait before throwing. Default 30 minutes (covers worst-case CCTP attestation). */
  timeoutMs?: number;
}

/**
 * waitForDelivery() — poll the destination vault until the swap is delivered.
 *
 * NOTE: standalone polling for SDK consumers without access to the daemon's
 * Redis state. Queries a bounded recent block window in pages to respect
 * public-RPC eth_getLogs limits.
 */
export async function waitForDelivery(
  swapId: Hash,
  opts: WaitForDeliveryOptions
): Promise<DeliveryStatus> {
  const { chain, pollIntervalMs = 5000, timeoutMs = 30 * 60 * 1000 } = opts;
  const vault = vaultFor(chain);
  const publicClient = publicClientFor(chain);

  // Verified against deployed TapVault.sol (contracts/src/TapVault.sol:46,48)
  const swapExecutedAbi = parseAbiItem(
    "event SwapExecuted(bytes32 indexed swapId, address indexed recipient, uint256 amountIn, uint256 payout, bool fronted)"
  );

  const start = Date.now();

  // Public RPCs cap eth_getLogs at a bounded block range (Base Sepolia: 2000).
  // Query a recent window backward from the current head in <=2000-block pages
  // rather than scanning all history.
  const MAX_RANGE = 1500n; // safety margin under the 2000 cap
  const LOOKBACK = 30000n; // ~how far back to search (covers delivery latency + buffer)

  while (Date.now() - start < timeoutMs) {
    const head = await publicClient.getBlockNumber();
    const earliest = head > LOOKBACK ? head - LOOKBACK : 0n;

    const getWindow = (from: bigint, to: bigint) =>
      publicClient.getLogs({
        address: vault,
        event: swapExecutedAbi,
        args: { swapId },
        fromBlock: from,
        toBlock: to,
      });

    let executedLogs: Awaited<ReturnType<typeof getWindow>> = [];
    for (let to = head; to >= earliest; to -= MAX_RANGE + 1n) {
      const from = to > earliest + MAX_RANGE ? to - MAX_RANGE : earliest;
      const logs = await getWindow(from, to);
      if (logs.length > 0) {
        executedLogs = logs;
        break;
      }
      if (from === earliest) break;
    }

    if (executedLogs.length > 0) {
      const fronted = executedLogs[0].args.fronted ?? false;

      let reconciled = !fronted;
      if (fronted) {
        const outstanding = await publicClient.readContract({
          address: vault,
          abi: VAULT_ABI,
          functionName: "outstandingFronted",
        });
        reconciled = outstanding === 0n;
      }

      return { delivered: true, fronted, reconciled };
    }

    await new Promise((r) => setTimeout(r, pollIntervalMs));
  }

  throw new Error(
    `waitForDelivery(): timed out after ${timeoutMs}ms waiting for swap ${swapId} on ${chain}`
  );
}
