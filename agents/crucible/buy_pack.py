"""buy_pack.py — buy 1 use of Crucible (listing 4) directly from the builder EOA.
Uses PRIVATE_KEY directly (NOT the revoked ZeroDev session key). Approves USDC, then buyPack.
"""
import os, time
from dotenv import load_dotenv
from web3 import Web3
load_dotenv("/home/dburnett11155/taprouter/.env.local")

RPC = "https://sepolia.base.org"
MARKET = Web3.to_checksum_address("0xBfd085f192d2246F1BFBe386DF399335dc894f2c")
USDC = Web3.to_checksum_address("0x036CbD53842c5426634e7929541eC2318f3dCF7e")
LISTING_ID = 4
NUM_USES = 1
CAP_PER_PERIOD = 10
PRICE_PER_USE = 250000  # 0.25 USDC

ERC20_ABI = [
    {"name":"approve","type":"function","stateMutability":"nonpayable",
     "inputs":[{"name":"s","type":"address"},{"name":"a","type":"uint256"}],"outputs":[{"name":"","type":"bool"}]},
    {"name":"allowance","type":"function","stateMutability":"view",
     "inputs":[{"name":"o","type":"address"},{"name":"s","type":"address"}],"outputs":[{"name":"","type":"uint256"}]},
]
MARKET_ABI = [
    {"name":"buyPack","type":"function","stateMutability":"nonpayable",
     "inputs":[{"name":"listingId","type":"uint256"},{"name":"numUses","type":"uint256"},{"name":"capPerPeriod","type":"uint64"}],"outputs":[]},
    {"name":"escrows","type":"function","stateMutability":"view",
     "inputs":[{"name":"","type":"uint256"},{"name":"","type":"address"}],
     "outputs":[{"name":"balance","type":"uint256"},{"name":"usesPurchased","type":"uint256"},{"name":"usesSettled","type":"uint256"},{"name":"capPerPeriod","type":"uint64"},{"name":"periodStart","type":"uint64"},{"name":"usedThisPeriod","type":"uint64"},{"name":"purchaseTime","type":"uint64"}]},
]

def send(w3, acct, tx):
    tx.update({"from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
               "maxFeePerGas": w3.to_wei(0.05,"gwei"), "maxPriorityFeePerGas": w3.to_wei(0.01,"gwei"),
               "chainId": 84532})
    s = acct.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(s.raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h)
    return h.hex(), r.status

def main():
    w3 = Web3(Web3.HTTPProvider(RPC))
    acct = w3.eth.account.from_key(os.getenv("PRIVATE_KEY"))
    usdc = w3.eth.contract(address=USDC, abi=ERC20_ABI)
    market = w3.eth.contract(address=MARKET, abi=MARKET_ABI)
    total = PRICE_PER_USE * NUM_USES
    print(f"Buyer: {acct.address}")
    print(f"Buying {NUM_USES} use(s) of listing {LISTING_ID} for {total/1e6} USDC")

    allowance = usdc.functions.allowance(acct.address, MARKET).call()
    if allowance < total:
        print("Approving USDC...")
        h, st = send(w3, acct, usdc.functions.approve(MARKET, total * 4).build_transaction({"gas":80000}))
        print(f"  approve tx {h} status {st}")
        if st != 1: print("APPROVE FAILED"); return

    print("Buying pack...")
    h, st = send(w3, acct, market.functions.buyPack(LISTING_ID, NUM_USES, CAP_PER_PERIOD).build_transaction({"gas":250000}))
    print(f"  buyPack tx {h} status {st}")
    if st != 1: print("BUYPACK FAILED — tx reverted"); return

    esc = market.functions.escrows(LISTING_ID, acct.address).call()
    print(f"Pack state — balance:{esc[0]} usesPurchased:{esc[1]} usesSettled:{esc[2]}")
    print(f"\nBOUGHT A CRUCIBLE PACK. {esc[1]-esc[2]} use(s) available to spend.")

if __name__ == "__main__":
    main()
