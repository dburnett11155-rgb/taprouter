"""list_on_market.py — register Crucible (advisory tier) as a listing on TapMarket (Base Sepolia).
Builder = deployer wallet (lists + receives payouts). agentSigner = Crucible's address.
"""
import os
from dotenv import load_dotenv
from web3 import Web3
load_dotenv("/home/dburnett11155/taprouter/.env.local")
RPC = "https://sepolia.base.org"
MARKET = Web3.to_checksum_address("0xBfd085f192d2246F1BFBe386DF399335dc894f2c")
PRICE_PER_USE = 250000           # 0.25 USDC (6 decimals) — advisory tier, deterministic
PAYOUT_EID = 0                   # same-chain (Base)
LIST_ABI = [{
    "name": "listAgent", "type": "function", "stateMutability": "nonpayable",
    "inputs": [
        {"name": "agentSigner", "type": "address"},
        {"name": "pricePerUse", "type": "uint256"},
        {"name": "payoutChainEid", "type": "uint32"}],
    "outputs": [{"name": "listingId", "type": "uint256"}],
}, {
    "name": "nextListingId", "type": "function", "stateMutability": "view",
    "inputs": [], "outputs": [{"name": "", "type": "uint256"}],
}]

def main():
    w3 = Web3(Web3.HTTPProvider(RPC))
    builder = w3.eth.account.from_key(os.getenv("PRIVATE_KEY"))
    crucible_addr = Web3.to_checksum_address(os.getenv("CRUCIBLE_ADDRESS"))
    market = w3.eth.contract(address=MARKET, abi=LIST_ABI)
    expected_id = market.functions.nextListingId().call()
    print(f"Builder:         {builder.address}")
    print(f"Crucible signer: {crucible_addr}")
    print(f"Price/use:       {PRICE_PER_USE} (0.25 USDC)")
    print(f"Expected listingId: {expected_id}")
    tx = market.functions.listAgent(crucible_addr, PRICE_PER_USE, PAYOUT_EID).build_transaction({
        "from": builder.address,
        "nonce": w3.eth.get_transaction_count(builder.address),
        "gas": 200000,
        "maxFeePerGas": w3.to_wei(0.05, "gwei"),
        "maxPriorityFeePerGas": w3.to_wei(0.01, "gwei"),
        "chainId": 84532,
    })
    signed = builder.sign_transaction(tx)
    txh = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"\nListing tx sent: {txh.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(txh)
    print(f"Status: {receipt.status} (1 = success)")
    if receipt.status == 1:
        print(f"Crucible listed as listingId {expected_id}")
        print(f"\nSave this: CRUCIBLE_LISTING_ID={expected_id}")
    else:
        print("LISTING FAILED — tx reverted")

if __name__ == "__main__":
    main()
