"""serve.py — Crucible ADVISORY tier as a paid service.
POST /audit {"contract_name","source","buyer"} -> verify payment -> run the DETERMINISTIC
layers (Slither + Aderyn ingest + finding-level triage, no LLM, no sandbox) on the submitted
source in a scratch foundry project -> attest + settle -> return structured findings.

Advisory tier: deterministic, cheap, seconds not minutes, NO badge. Mirrors Scribe's async
job pattern so the certification tier (full ladder) can reuse this skeleton later.
"""
import os, json, time, uuid, threading, pathlib, shutil, subprocess, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from web3 import Web3
load_dotenv("/home/dburnett11155/taprouter/.env.local")
from attest import sign_attestation

RPC = "https://sepolia.base.org"
MARKET = Web3.to_checksum_address("0xBfd085f192d2246F1BFBe386DF399335dc894f2c")
LISTING_ID = int(os.getenv("CRUCIBLE_LISTING_ID", "0"))
AUDITOR = pathlib.Path("/home/dburnett11155/taprouter/auditor")
REAL_CONTRACTS = pathlib.Path("/home/dburnett11155/taprouter/contracts")
OUTDIR = pathlib.Path("/home/dburnett11155/taprouter/agents/crucible/completed"); OUTDIR.mkdir(exist_ok=True)
SUBDIR = pathlib.Path("/home/dburnett11155/taprouter/agents/crucible/submitted"); SUBDIR.mkdir(exist_ok=True)

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
JOBS = {}; JOBS_LOCK = threading.Lock()


def run_advisory_audit(contract_name, source):
    """Build a scratch foundry project from submitted source, run deterministic layers only."""
    work = SUBDIR / uuid.uuid4().hex[:8]
    work.mkdir(parents=True)
    # scratch project: real foundry.toml + symlinked lib/ so imports resolve, isolated src/
    for f in ("foundry.toml", "remappings.txt"):
        if (REAL_CONTRACTS / f).exists():
            shutil.copy(REAL_CONTRACTS / f, work / f)
    (work / "src").mkdir()
    fname = contract_name if contract_name.endswith(".sol") else contract_name + ".sol"
    (work / "src" / fname).write_text(source)
    if (REAL_CONTRACTS / "lib").exists():
        os.symlink(REAL_CONTRACTS / "lib", work / "lib")
    # Advisory = PURELY DETERMINISTIC scanner findings. No Red/White/Judge debate (that is
    # LLM cost and would strand findings at needs_sandbox), no exploit sandbox, no invariants.
    # Just Slither + Aderyn, deduplicated, handed to the buyer's own AI — exactly the two-tier
    # design: advisory hands off tool findings; certification runs the engine.
    sys.path.insert(0, str(AUDITOR))
    import importlib, config as _cfg
    _cfg.FOUNDRY_ROOT = work
    _cfg.OUT_DIR = work / "out"
    from ingest import runner as ingest_runner; importlib.reload(ingest_runner)
    bundle = ingest_runner.audit(f"src/{fname}", deep=False)
    findings = [{"file": f["file"], "lines": f.get("lines"), "severity": f["severity"],
                 "detectors": f.get("check_ids", f.get("check_id")),
                 "description": f.get("description", "")[:400]}
                for f in bundle["findings"]]
    return {"contract": contract_name,
            "by_severity": bundle.get("by_severity"),
            "total_findings": bundle.get("total"),
            "findings": findings,
            "tier": "advisory",
            "note": "Advisory tier: deterministic Slither + Aderyn findings handed to you for "
                    "review by your own AI. No adjudication, no certification badge, not a proof "
                    "of safety. Upgrade to the certification tier for the full verdict engine."}


def run_job(job_id, body, buyer, esc):
    try:
        result = run_advisory_audit(body["contract_name"], body["source"])
        (OUTDIR / f"{job_id}.json").write_text(json.dumps({"buyer": buyer, "request": {"contract_name": body["contract_name"]}, "audit": result}))
        cumulative = esc[2] + 1
        expiry = int(time.time()) + 3600
        sig = sign_attestation(buyer, LISTING_ID, cumulative, expiry)
        tx = market.functions.settle(LISTING_ID, buyer, cumulative, expiry, sig).build_transaction({
            "from": relayer.address, "nonce": w3.eth.get_transaction_count(relayer.address, "pending"),
            "gas": 300000, "maxFeePerGas": w3.to_wei(0.05, "gwei"),
            "maxPriorityFeePerGas": w3.to_wei(0.01, "gwei"), "chainId": 84532})
        stx = relayer.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(stx.raw_transaction)
        rcpt = w3.eth.wait_for_transaction_receipt(h)
        if rcpt.status != 1:
            with JOBS_LOCK: JOBS[job_id] = {"status": "failed", "error": "settlement reverted - no charge collected"}
            return
        with JOBS_LOCK: JOBS[job_id] = {"status": "done", "audit": result, "settleTx": h.hex(), "use": cumulative}
        print(f"[crucible] job {job_id} done, settled use #{cumulative}", flush=True)
    except Exception as e:
        with JOBS_LOCK: JOBS[job_id] = {"status": "failed", "error": str(e)}
        print(f"[crucible] job {job_id} FAILED: {e}", flush=True)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not self.path.startswith("/result/"):
            self.send_response(404); self.end_headers(); return
        if self.headers.get("Authorization") != f"Bearer {os.getenv('TAP_SERVICE_TOKEN')}":
            self.send_response(401); self.end_headers(); self.wfile.write(b'{"error":"unauthorized"}'); return
        job_id = self.path.split("/result/")[1]
        with JOBS_LOCK: job = JOBS.get(job_id)
        if job is None:
            f = OUTDIR / f"{job_id}.json"
            if f.exists(): job = {"status": "done", **json.loads(f.read_text())}
            else:
                self.send_response(404); self.end_headers(); self.wfile.write(b'{"error":"unknown job"}'); return
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps(job).encode())

    def do_POST(self):
        if self.path != "/audit":
            self.send_response(404); self.end_headers(); return
        if self.headers.get("Authorization") != f"Bearer {os.getenv('TAP_SERVICE_TOKEN')}":
            self.send_response(401); self.end_headers(); self.wfile.write(b'{"error":"unauthorized"}'); return
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        body = json.loads(raw)
        buyer = Web3.to_checksum_address(body["buyer"])
        esc = market.functions.escrows(LISTING_ID, buyer).call()
        if esc[1] <= esc[2]:
            self.send_response(402); self.end_headers(); self.wfile.write(b'{"error":"no unused pack - buy first"}'); return
        job_id = uuid.uuid4().hex[:12]
        with JOBS_LOCK: JOBS[job_id] = {"status": "working"}
        threading.Thread(target=run_job, args=(job_id, body, buyer, esc), daemon=True).start()
        print(f"[crucible] job {job_id} accepted: '{body['contract_name']}' for {buyer}", flush=True)
        self.send_response(202); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps({"job_id": job_id, "status": "working", "poll": f"/result/{job_id}"}).encode())


if __name__ == "__main__":
    print("Crucible advisory service on http://127.0.0.1:8789 — deterministic contract audit", flush=True)
    HTTPServer(("127.0.0.1", 8789), Handler).serve_forever()
