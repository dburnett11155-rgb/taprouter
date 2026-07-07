// wallet-store.js — single canonical wallet module for tapmarket-connect.
// Resolution: TAPMARKET_WALLET env override, else ~/.tapmarket/wallet.json.
// ownerKey may be encrypted at rest (scrypt + AES-256-GCM). sessionApproval
// and authKey stay serve-readable by design: the unattended server signs
// requests with authKey (holds nothing) and spends via the session policy
// (TapMarket-only, revocable). ownerKey is needed only for interactive
// owner ops and is never required by `serve`.
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "fs";
import { homedir } from "os";
import { join, dirname } from "path";
import { randomBytes, scryptSync, createCipheriv, createDecipheriv } from "crypto";

const SCRYPT = { N: 1 << 15, r: 8, p: 1, maxmem: 64 * 1024 * 1024 };

export function resolveWalletPath() {
  const env = process.env.TAPMARKET_WALLET;
  return { path: env ?? join(homedir(), ".tapmarket", "wallet.json"), source: env ? "env:TAPMARKET_WALLET" : "default" };
}

export function loadWallet({ quiet = false } = {}) {
  const { path, source } = resolveWalletPath();
  if (!existsSync(path)) return { wallet: null, path, source };
  const wallet = JSON.parse(readFileSync(path, "utf8"));
  if (!quiet) console.error(`tapmarket: wallet ${wallet.smartAccount} (${source}: ${path})`);
  return { wallet, path, source };
}

export function saveWallet(path, wallet) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(wallet, null, 2), { mode: 0o600 });
}

export function isOwnerKeyEncrypted(wallet) {
  return !!wallet.ownerKeyEnc && !wallet.ownerKey;
}

export function encryptOwnerKey(plainHexKey, passphrase) {
  const salt = randomBytes(16);
  const key = scryptSync(passphrase, salt, 32, SCRYPT);
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  const ct = Buffer.concat([cipher.update(plainHexKey, "utf8"), cipher.final()]);
  return {
    v: 1, kdf: "scrypt", N: SCRYPT.N, r: SCRYPT.r, p: SCRYPT.p,
    salt: salt.toString("base64"), iv: iv.toString("base64"),
    ct: ct.toString("base64"), tag: cipher.getAuthTag().toString("base64"),
  };
}

export function decryptOwnerKey(enc, passphrase) {
  if (enc.v !== 1 || enc.kdf !== "scrypt") throw new Error(`unsupported ownerKeyEnc format (v=${enc.v} kdf=${enc.kdf})`);
  const key = scryptSync(passphrase, Buffer.from(enc.salt, "base64"), 32, { N: enc.N, r: enc.r, p: enc.p, maxmem: SCRYPT.maxmem });
  const decipher = createDecipheriv("aes-256-gcm", key, Buffer.from(enc.iv, "base64"));
  decipher.setAuthTag(Buffer.from(enc.tag, "base64"));
  try {
    return Buffer.concat([decipher.update(Buffer.from(enc.ct, "base64")), decipher.final()]).toString("utf8");
  } catch {
    throw new Error("wrong passphrase (or corrupted wallet file)");
  }
}

// Interactive passphrase prompt, input hidden. TTY-only by design:
// serve must never call this — if it ever does, failing loudly here is correct.
export function promptPassphrase(promptText = "Passphrase: ") {
  if (!process.stdin.isTTY) throw new Error("passphrase required but no interactive terminal available");
  return new Promise((resolve, reject) => {
    process.stderr.write(promptText);
    const stdin = process.stdin;
    stdin.setRawMode(true); stdin.resume(); stdin.setEncoding("utf8");
    let buf = "";
    const onData = (ch) => {
      if (ch === "\r" || ch === "\n") {
        stdin.setRawMode(false); stdin.pause(); stdin.removeListener("data", onData);
        process.stderr.write("\n"); resolve(buf);
      } else if (ch === "\u0003") { // Ctrl-C
        stdin.setRawMode(false); stdin.pause(); stdin.removeListener("data", onData);
        process.stderr.write("\n"); reject(new Error("cancelled"));
      } else if (ch === "\u007f" || ch === "\b") {
        buf = buf.slice(0, -1);
      } else {
        buf += ch;
      }
    };
    stdin.on("data", onData);
  });
}

// Unlock ownerKey for an owner op: prompts if encrypted, passes through if legacy plaintext.
export async function unlockOwnerKey(wallet, promptText = "Wallet passphrase: ") {
  if (wallet.ownerKey) return wallet.ownerKey; // legacy plaintext — migration handled by cli
  if (wallet.ownerKeyEnc) return decryptOwnerKey(wallet.ownerKeyEnc, await promptPassphrase(promptText));
  throw new Error("wallet has no ownerKey or ownerKeyEnc field");
}
