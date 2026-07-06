"""Tap testnet auto-faucet. POST /fund {"address":"0x.."} -> drips 1 USDC + 0.001 ETH.
Rules: once per address ever, 5 per IP per day. Deployer-funded, testnet only."""
import os, json, time, re
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from web3 import Web3

load_dotenv("/home/dburnett11155/taprouter/.env.local")
RPC = "https://sepolia.base.org"
USDC = Web3.to_checksum_address("0x036CbD53842c5426634e7929541eC2318f3dCF7e")
DRIP_USDC = 1_000_000          # $1
DRIP_ETH = Web3.to_wei(0.001, "ether")
LEDGER = "/home/dburnett11155/taprouter/faucet/ledger.jsonl"

w3 = Web3(Web3.HTTPProvider(RPC))
funder = w3.eth.account.from_key(os.getenv("PRIVATE_KEY"))
usdc = w3.eth.contract(address=USDC, abi=[{"name":"transfer","type":"function","stateMutability":"nonpayable","inputs":[{"name":"to","type":"address"},{"name":"value","type":"uint256"}],"outputs":[{"name":"","type":"bool"}]}])

def load_ledger():
    seen_addr, ip_counts = set(), {}
    day_ago = time.time() - 86400
    try:
        for line in open(LEDGER):
            r = json.loads(line)
            seen_addr.add(r["address"].lower())
            if r["ts"] > day_ago:
                ip_counts[r["ip"]] = ip_counts.get(r["ip"], 0) + 1
    except FileNotFoundError:
        pass
    return seen_addr, ip_counts

REGISTRY = "/home/dburnett11155/taprouter/faucet/registry.json"

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/registry":
            self.send_response(404); self.end_headers(); return
        try:
            body = open(REGISTRY, "rb").read()
            json.loads(body)  # never serve broken JSON
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "max-age=300")
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            self.send_response(500); self.end_headers()

    def _reply(self, code, obj):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def do_POST(self):
        if self.path != "/fund":
            self._reply(404, {"error": "not found"}); return
        try:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            addr = body["address"]
            assert re.fullmatch(r"0x[0-9a-fA-F]{40}", addr)
        except Exception:
            self._reply(400, {"error": "bad request"}); return
        addr = Web3.to_checksum_address(addr)
        ip = self.headers.get("CF-Connecting-IP", self.client_address[0])
        seen, ips = load_ledger()
        if addr.lower() in seen:
            self._reply(429, {"error": "address already funded"}); return
        if ips.get(ip, 0) >= 5:
            self._reply(429, {"error": "daily limit reached"}); return
        try:
            nonce = w3.eth.get_transaction_count(funder.address, "pending")
            tx1 = usdc.functions.transfer(addr, DRIP_USDC).build_transaction({
                "from": funder.address, "nonce": nonce, "gas": 80000,
                "maxFeePerGas": w3.to_wei(0.05, "gwei"), "maxPriorityFeePerGas": w3.to_wei(0.01, "gwei"), "chainId": 84532})
            h1 = w3.eth.send_raw_transaction(funder.sign_transaction(tx1).raw_transaction)
            tx2 = {"from": funder.address, "to": addr, "value": DRIP_ETH, "nonce": nonce + 1, "gas": 21000,
                   "maxFeePerGas": w3.to_wei(0.05, "gwei"), "maxPriorityFeePerGas": w3.to_wei(0.01, "gwei"), "chainId": 84532}
            h2 = w3.eth.send_raw_transaction(funder.sign_transaction(tx2).raw_transaction)
            w3.eth.wait_for_transaction_receipt(h2)
            with open(LEDGER, "a") as f:
                f.write(json.dumps({"ts": time.time(), "address": addr, "ip": ip, "usdc_tx": h1.hex(), "eth_tx": h2.hex()}) + "\n")
            print(f"[faucet] dripped to {addr} ({ip})", flush=True)
            self._reply(200, {"funded": True, "usdc": "1.00", "eth": "0.001", "usdc_tx": h1.hex(), "eth_tx": h2.hex()})
        except Exception as e:
            print(f"[faucet] FAIL {addr}: {e}", flush=True)
            self._reply(500, {"error": "faucet error"})

print("Tap faucet on http://127.0.0.1:8790", flush=True)
HTTPServer(("127.0.0.1", 8790), Handler).serve_forever()
