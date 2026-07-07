"""serve.py — Scribe as a paid service. POST /write {"topic","keyword","links",[{name,url}],"buyer"}
→ verifies payment on-chain → writes the article (Qwen) → attests + settles → returns article."""
import os, json, time, uuid, threading, pathlib
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from web3 import Web3
from writer import write_article
from attest import sign_attestation

load_dotenv("/home/dburnett11155/taprouter/.env.local")
RPC = "https://sepolia.base.org"
MARKET = Web3.to_checksum_address("0xBfd085f192d2246F1BFBe386DF399335dc894f2c")
LISTING_ID = int(os.getenv("SCRIBE_LISTING_ID"))
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
OUTDIR = pathlib.Path("/home/dburnett11155/taprouter/agents/scribe/completed")
OUTDIR.mkdir(exist_ok=True)
JOBS = {}  # job_id -> {"status": "working"|"done"|"failed", ...result}
JOBS_LOCK = threading.Lock()

def run_job(job_id, body, buyer, esc):
    try:
        article = write_article(body["topic"], body["keyword"], body["links"])
        (OUTDIR / f"{job_id}.json").write_text(json.dumps({"buyer": buyer, "request": body, "article": article}))
        cumulative = esc[2] + 1
        expiry = int(time.time()) + 3600
        sig = sign_attestation(buyer, LISTING_ID, cumulative, expiry)
        tx = market.functions.settle(LISTING_ID, buyer, cumulative, expiry, sig).build_transaction({
            "from": relayer.address, "nonce": w3.eth.get_transaction_count(relayer.address, "pending"),
            "gas": 300000, "maxFeePerGas": w3.to_wei(0.05, "gwei"),
            "maxPriorityFeePerGas": w3.to_wei(0.01, "gwei"), "chainId": 84532,
        })
        stx = relayer.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(stx.raw_transaction)
        rcpt = w3.eth.wait_for_transaction_receipt(h)
        if rcpt.status != 1:
            with JOBS_LOCK: JOBS[job_id] = {"status": "failed", "error": "settlement reverted - no charge collected"}
            return
        with JOBS_LOCK: JOBS[job_id] = {"status": "done", "article": article, "settleTx": h.hex(), "use": cumulative}
        print(f"[scribe] job {job_id} done, settled use #{cumulative}", flush=True)
    except Exception as e:
        with JOBS_LOCK: JOBS[job_id] = {"status": "failed", "error": str(e)}
        print(f"[scribe] job {job_id} FAILED: {e}", flush=True)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not self.path.startswith("/result/"):
            self.send_response(404); self.end_headers(); return
        if self.headers.get("Authorization") != f"Bearer {os.getenv('TAP_SERVICE_TOKEN')}":
            self.send_response(401); self.end_headers()
            self.wfile.write(b'{"error":"unauthorized"}'); return
        job_id = self.path.split("/result/")[1]
        with JOBS_LOCK: job = JOBS.get(job_id)
        if job is None:
            f = OUTDIR / f"{job_id}.json"
            if f.exists():
                job = {"status": "done", **json.loads(f.read_text())}
            else:
                self.send_response(404); self.end_headers()
                self.wfile.write(b'{"error":"unknown job"}'); return
        self.send_response(200)
        self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps(job).encode())

    def do_POST(self):
        if self.path != "/write":
            self.send_response(404); self.end_headers(); return
        if self.headers.get("Authorization") != f"Bearer {os.getenv('TAP_SERVICE_TOKEN')}":
            self.send_response(401); self.end_headers()
            self.wfile.write(b'{"error":"unauthorized"}'); return
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        from verify import check_signature
        auth = check_signature(self.headers, raw)
        print(f"[auth] {auth['reason']} (signer: {auth['signer']})", flush=True)
        body = json.loads(raw)
        buyer = Web3.to_checksum_address(body["buyer"])

        esc = market.functions.escrows(LISTING_ID, buyer).call()
        if esc[1] <= esc[2]:
            self.send_response(402); self.end_headers()
            self.wfile.write(b'{"error":"no unused pack - buy first"}'); return

        job_id = uuid.uuid4().hex[:12]
        with JOBS_LOCK: JOBS[job_id] = {"status": "working"}
        threading.Thread(target=run_job, args=(job_id, body, buyer, esc), daemon=True).start()
        print(f"[scribe] job {job_id} accepted: '{body['topic']}' for {buyer}", flush=True)
        self.send_response(202)
        self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps({"job_id": job_id, "status": "working", "poll": f"/result/{job_id}"}).encode())

print("Scribe service on http://127.0.0.1:8788 — paid affiliate content", flush=True)
HTTPServer(("127.0.0.1", 8788), Handler).serve_forever()
