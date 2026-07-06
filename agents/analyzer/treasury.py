"""treasury.py — Hermes's earnings management. THE PATTERN, not a product:
an agent's own wallet commits ITS OWN earnings to the LP vault, keeping an
operating float. Builders copy this for their agents. Never pooled, never
custodial — the agent's key, the agent's money, the agent's position.

Usage:  python treasury.py status | sweep
"""
import os, sys, time
from dotenv import load_dotenv
from web3 import Web3

load_dotenv("/home/dburnett11155/taprouter/.env.local")
RPC = "https://sepolia.base.org"
USDC = Web3.to_checksum_address("0x036CbD53842c5426634e7929541eC2318f3dCF7e")
VAULT = Web3.to_checksum_address("0x1360d65342b1F9543ce2A69e07076efE75657025")
FLOAT_UNITS = 1_000_000  # keep $1 operating float; LP the rest

w3 = Web3(Web3.HTTPProvider(RPC))
acct = w3.eth.account.from_key(os.environ["HERMES_PRIVATE_KEY"])
usdc = w3.eth.contract(address=USDC, abi=[
    {"name": "balanceOf", "type": "function", "stateMutability": "view", "inputs": [{"name": "", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}]},
    {"name": "approve", "type": "function", "stateMutability": "nonpayable", "inputs": [{"name": "spender", "type": "address"}, {"name": "value", "type": "uint256"}], "outputs": [{"name": "", "type": "bool"}]},
])
vault = w3.eth.contract(address=VAULT, abi=[
    {"name": "deposit", "type": "function", "stateMutability": "nonpayable", "inputs": [{"name": "amount", "type": "uint256"}], "outputs": []},
    {"name": "shares", "type": "function", "stateMutability": "view", "inputs": [{"name": "", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}]},
    {"name": "pendingFees", "type": "function", "stateMutability": "view", "inputs": [{"name": "lp", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}]},
])

def send(fn):
    tx = fn.build_transaction({"from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
                               "gas": 200000, "maxFeePerGas": w3.to_wei(0.05, "gwei"),
                               "maxPriorityFeePerGas": w3.to_wei(0.01, "gwei"), "chainId": 84532})
    h = w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h)
    assert r.status == 1, f"tx reverted: {h.hex()}"
    return h.hex()

def status():
    bal = usdc.functions.balanceOf(acct.address).call()
    sh = vault.functions.shares(acct.address).call()
    fees = vault.functions.pendingFees(acct.address).call()
    print(f"Hermes treasury ({acct.address})")
    print(f"  wallet USDC:     ${bal/1e6:.2f}")
    print(f"  LP shares:       {sh/1e6:.2f}")
    print(f"  unclaimed fees:  ${fees/1e6:.4f}")

def sweep():
    bal = usdc.functions.balanceOf(acct.address).call()
    excess = bal - FLOAT_UNITS
    if excess <= 0:
        print(f"Nothing to sweep (balance ${bal/1e6:.2f} <= float ${FLOAT_UNITS/1e6:.2f})"); return
    print(f"Sweeping ${excess/1e6:.2f} into TapVault (keeping ${FLOAT_UNITS/1e6:.2f} float)...")
    print("  approve:", send(usdc.functions.approve(VAULT, excess)))
    time.sleep(2)
    print("  deposit:", send(vault.functions.deposit(excess)))
    status()

if __name__ == "__main__":
    {"status": status, "sweep": sweep}.get(sys.argv[1] if len(sys.argv) > 1 else "status", status)()
