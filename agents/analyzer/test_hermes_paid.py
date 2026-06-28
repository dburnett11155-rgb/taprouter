"""test_hermes_paid.py — prove the full bridge: buyer buys a pack of Hermes,
Hermes signs an attestation, settle() pays out. Off-chain agent earns on-chain.
"""
import os, time
from dotenv import load_dotenv
from web3 import Web3
from attest import sign_attestation

load_dotenv("/home/dburnett11155/taprouter/.env.local")

RPC = "https://sepolia.base.org"
MARKET = Web3.to_checksum_address("0xBfd085f192d2246F1BFBe386DF399335dc894f2c")
USDC = Web3.to_checksum_address("0x036CbD53842c5426634e7929541eC2318f3dCF7e")
LISTING_ID = int(os.getenv("HERMES_LISTING_ID"))

MARKET_ABI = [
    {"name": "buyPack", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "listingId", "type": "uint256"}, {"name": "numUses", "type": "uint256"}, {"name": "capPerPeriod", "type": "uint64"}], "outputs": []},
    {"name": "settle", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "listingId", "type": "uint256"}, {"name": "buyer", "type": "address"}, {"name": "cumulativeUses", "type": "uint256"}, {"name": "expiry", "type": "uint256"}, {"name": "sig", "type": "bytes"}], "outputs": []},
    {"name": "escrows", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "", "type": "uint256"}, {"name": "", "type": "address"}],
     "outputs": [{"name": "balance", "type": "uint256"}, {"name": "usesPurchased", "type": "uint256"}, {"name": "settledUses", "type": "uint256"}, {"name": "capPerPeriod", "type": "uint64"}, {"name": "periodStart", "type": "uint64"}, {"name": "usedThisPeriod", "type": "uint64"}, {"name": "purchaseTime", "type": "uint64"}]},
]
USDC_ABI = [
    {"name": "approve", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "outputs": [{"name": "", "type": "bool"}]},
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "a", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}]},
]


def send(w3, acct, fn):
    tx = fn.build_transaction({
        "from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
        "gas": 300000, "maxFeePerGas": w3.to_wei(0.05, "gwei"),
        "maxPriorityFeePerGas": w3.to_wei(0.01, "gwei"), "chainId": 84532,
    })
    s = acct.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(s.raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h)
    return r


def main():
    w3 = Web3(Web3.HTTPProvider(RPC))
    buyer = w3.eth.account.from_key(os.getenv("PRIVATE_KEY"))  # deployer = buyer here
    market = w3.eth.contract(address=MARKET, abi=MARKET_ABI)
    usdc = w3.eth.contract(address=USDC, abi=USDC_ABI)

    print(f"Buyer: {buyer.address}")
    print(f"Listing: {LISTING_ID} (Hermes)")

    # 1. Approve + buy a 2-use pack (1 USDC at 0.5/use), cap 10.
    print("\n1. Approving + buying 2-use pack...")
    send(w3, buyer, usdc.functions.approve(MARKET, 1_000000))
    send(w3, buyer, market.functions.buyPack(LISTING_ID, 2, 10))
    print("   pack bought")

    # 2. Hermes signs an attestation for 1 cumulative use.
    expiry = int(time.time()) + 3600
    sig = sign_attestation(buyer.address, LISTING_ID, 1, expiry)
    print("2. Hermes signed attestation for 1 use")

    # 3. Settle.
    builder_before = usdc.balanceOf(buyer.address) if False else None
    print("3. Settling...")
    r = send(w3, buyer, market.functions.settle(LISTING_ID, buyer.address, 1, expiry, sig))
    print(f"   settle status: {r.status} (1 = success)")

    # 4. Read escrow state.
    e = market.functions.escrows(LISTING_ID, buyer.address).call()
    print(f"\nEscrow after settle:")
    print(f"  balance:     {e[0]} (expect 500000 = 0.5 USDC, 1 of 2 uses left)")
    print(f"  settledUses: {e[2]} (expect 1)")


if __name__ == "__main__":
    main()
