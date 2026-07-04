"""list_on_market.py — register Scribe as a listing on TapMarket (Base Sepolia).

Builder = deployer wallet (lists + receives payouts).
agentSigner = Scribe's address (signs use-attestations).
"""
import os
from dotenv import load_dotenv
from web3 import Web3

load_dotenv("/home/dburnett11155/taprouter/.env.local")

RPC = "https://sepolia.base.org"
MARKET = Web3.to_checksum_address("0xBfd085f192d2246F1BFBe386DF399335dc894f2c")
PRICE_PER_USE = 1000000          # 0.5 USDC (6 decimals)
PAYOUT_EID = 0                  # same-chain (Base)

LIST_ABI = [{
    "name": "listAgent",
    "type": "function",
    "stateMutability": "nonpayable",
    "inputs": [
        {"name": "agentSigner", "type": "address"},
        {"name": "pricePerUse", "type": "uint256"},
        {"name": "payoutChainEid", "type": "uint32"},
    ],
    "outputs": [{"name": "listingId", "type": "uint256"}],
}, {
    "name": "nextListingId",
    "type": "function",
    "stateMutability": "view",
    "inputs": [],
    "outputs": [{"name": "", "type": "uint256"}],
}]


def main():
    w3 = Web3(Web3.HTTPProvider(RPC))
    builder_key = os.getenv("PRIVATE_KEY")
    scribe_addr = Web3.to_checksum_address(os.getenv("SCRIBE_ADDRESS"))
    builder = w3.eth.account.from_key(builder_key)

    market = w3.eth.contract(address=MARKET, abi=LIST_ABI)

    # The listingId will be the current nextListingId.
    expected_id = market.functions.nextListingId().call()
    print(f"Builder:       {builder.address}")
    print(f"Scribe signer: {scribe_addr}")
    print(f"Price/use:     {PRICE_PER_USE} (1 USDC)")
    print(f"Expected listingId: {expected_id}")

    tx = market.functions.listAgent(scribe_addr, PRICE_PER_USE, PAYOUT_EID).build_transaction({
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
    print(f"Scribe listed as listingId {expected_id}")
    print(f"\nSave this: SCRIBE_LISTING_ID={expected_id}")


if __name__ == "__main__":
    main()
