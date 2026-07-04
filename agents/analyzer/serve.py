"""serve.py — Hermes as a paid service. POST /assess {"address": "..", "buyer": ".."}
→ runs the real Qwen assessment → signs attestation for buyer's next use → settles on-chain
→ returns the assessment + settle tx. Hermes earns for real work."""
import os, json, time
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from web3 import Web3
from hermes import assess
from attest import sign_attestation

load_dotenv("/home/dburnett11155/taprouter/.env.local")
RPC = "https://sepolia.base.org"
MARKET = Web3.to_checksum_address("0xBfd085f192d2246F1BFBe386DF399335dc894f2c")
LISTING_ID = int(os.getenv("HERMES_LISTING_ID"))
MARKET_ABI = [
    {"name": "settle", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "listingId", "type": "uint256"}, {"name": "buyer", "type": "address"}, {"name": "cumulativeUses", "type": "uint256"}, {"name": "expiry", "type": "uint256"}, {"name": "sig", "type": "bytes"}], "outputs": []},
    {"name": "escrows", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "", "type": "uint256"}, {"name": "", "type": "address"}],
     "outputs": [{"name": "balance", "type": "uint256"}, {"name": "usesPurchased", "type": "uint256"}, {"name": "settledUses", "type": "uint256"}, {"name": "capPerPeriod", "type": "uint64"}, {"name": "periodStart", "type": "uint64"}, {"name": "usedThisPeriod", "type": "uint64"}, {"name": "purchaseTime", "type": "uint64"}]},
]

w3 = Web3(Web3.HTTPProvider(RPC))
market = w3.eth.contract(address=MARKET, abi=MARKET_ABI)
relayer = w3.eth.account.from_key(os.getenv("PRIVATE_KEY"))

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/assess":
            self.send_response(404); self.end_headers(); return
        if self.headers.get("Authorization") != f"Bearer {os.getenv('TAP_SERVICE_TOKEN')}":
            self.send_response(401); self.end_headers()
            self.wfile.write(b'{"error":"unauthorized"}'); return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        target, buyer = body["address"], Web3.to_checksum_address(body["buyer"])

        esc = market.functions.escrows(LISTING_ID, buyer).call()
        if esc[1] <= esc[2]:
            self.send_response(402); self.end_headers()
            self.wfile.write(b'{"error":"no unused pack - buy first"}'); return

        print(f"[hermes] paid job: assess {target} for {buyer}", flush=True)
        result = assess(target)

        cumulative = esc[2] + 1
        expiry = int(time.time()) + 3600
        sig = sign_attestation(buyer, LISTING_ID, cumulative, expiry)
        tx = market.functions.settle(LISTING_ID, buyer, cumulative, expiry, sig).build_transaction({
            "from": relayer.address, "nonce": w3.eth.get_transaction_count(relayer.address, "pending"),
            "gas": 300000, "maxFeePerGas": w3.to_wei(0.05, "gwei"),
            "maxPriorityFeePerGas": w3.to_wei(0.01, "gwei"), "chainId": 84532,
        })
        s = relayer.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(s.raw_transaction)
        w3.eth.wait_for_transaction_receipt(h)
        print(f"[hermes] settled use #{cumulative}: {h.hex()}", flush=True)

        self.send_response(200)
        self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps({"assessment": result, "settleTx": h.hex(), "use": cumulative}).encode())

print("Hermes service on http://127.0.0.1:8787 — real work, real pay", flush=True)
HTTPServer(("127.0.0.1", 8787), Handler).serve_forever()
