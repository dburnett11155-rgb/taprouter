"""certify_serve.py — CERTIFICATION tier (port 8790).

POST /certify {"contract_name","source","buyer"} -> verify payment -> run the FULL LADDER
(ingest -> Red/White/Judge -> exploit sandbox -> mutation-validated invariants) -> attest +
settle -> return verdict JSON + layman's explanation + signed SAFETY BADGE.

Contrast with advisory (serve.py, 8789): advisory is deterministic scanners only, proof-of-run,
no badge. Certification runs the engine and issues a safety badge that reflects the REAL verdict
(certifies only if the ladder confirmed no defect). Reuses the proven settle/escrow plumbing.
"""
import os, json, time, uuid, threading, pathlib, shutil, sys, importlib
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from web3 import Web3

load_dotenv("/home/dburnett11155/taprouter/.env.local")

sys.path.insert(0, "/home/dburnett11155/taprouter/agents/crucible")
from attest import sign_attestation, sign_badge
import explain as explain_mod

RPC = "https://sepolia.base.org"
MARKET = Web3.to_checksum_address("0xBfd085f192d2246F1BFBe386DF399335dc894f2c")
CERTIFY_LISTING_ID = int(os.getenv("CRUCIBLE_CERTIFY_LISTING_ID", "0"))
AUDITOR = pathlib.Path("/home/dburnett11155/taprouter/auditor")
REAL_CONTRACTS = pathlib.Path("/home/dburnett11155/taprouter/contracts")
OUTDIR = pathlib.Path("/home/dburnett11155/taprouter/agents/crucible/certified"); OUTDIR.mkdir(exist_ok=True)
SUBDIR = pathlib.Path("/home/dburnett11155/taprouter/agents/crucible/cert_submitted"); SUBDIR.mkdir(exist_ok=True)

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


def run_certification(contract_name, source):
    """Build a scratch foundry project and run the FULL ladder (sandbox + invariants)."""
    work = SUBDIR / uuid.uuid4().hex[:8]
    work.mkdir(parents=True)
    for f in ("foundry.toml", "remappings.txt"):
        if (REAL_CONTRACTS / f).exists():
            shutil.copy(REAL_CONTRACTS / f, work / f)
    (work / "src").mkdir()
    fname = contract_name if contract_name.endswith(".sol") else contract_name + ".sol"
    (work / "src" / fname).write_text(source)
    if (REAL_CONTRACTS / "lib").exists():
        os.symlink(REAL_CONTRACTS / "lib", work / "lib")
    sys.path.insert(0, str(AUDITOR))
    import config as _cfg
    _cfg.FOUNDRY_ROOT = work
    _cfg.OUT_DIR = work / "out"
    (work / "out").mkdir(exist_ok=True)
    import crucible as _crucible; importlib.reload(_crucible)
    report = _crucible.audit(f"src/{fname}", do_sandbox=True, do_invariants=True)
    result = {
        "contract": contract_name,
        "tier": "certification",
        "badge_eligible": report.get("badge_eligible"),
        "verdict": {
            "scanned": report.get("scanned"),
            "adjudicated": report.get("adjudicated"),
            "confirmed_defects": report.get("confirmed_defects"),
            "unresolved": report.get("unresolved"),
            "disputed": report.get("disputed"),
            "invariants_violated": report.get("invariants_violated"),
            "invariants_held": report.get("invariants_held"),
            "verdicts": report.get("verdicts"),
            "invariant_findings": report.get("invariant_findings"),
        },
        "badge_scope": report.get("badge_scope"),
    }
    # findings list for the explanation (from the verdicts)
    _CLEARED = {"cleared_by_debate", "cleared_by_failed_exploit", "INVARIANT_HELD"}
    _annotated = []
    for v in report.get("verdicts", []):
        disp = v.get("disposition", "")
        _annotated.append({
            "lines": v.get("lines"), "severity": v.get("severity"),
            "detectors": v.get("detectors"), "disposition": disp,
            "adjudication": ("CLEARED by engine review — scanner raised this, adversarial debate/exploit testing found it NOT exploitable" if disp in _CLEARED else "STANDS — not cleared by the engine; a genuine concern"),
        })
    result["findings"] = _annotated
    result["total_findings"] = report.get("adjudicated")
    result["confirmed_defects"] = report.get("confirmed_defects")
    try:
        result["explanation"] = explain_mod.explain(result, certified=True)
    except Exception:
        result["explanation"] = {"summary": "(unavailable)", "bottom_line": result.get("badge_scope", "")}
    try:
        result["badge"] = sign_badge(contract_name, report)
    except Exception as e:
        result["badge"] = {"error": "badge unavailable: %s" % str(e)[:100]}
    return result


def run_job(job_id, body, buyer, esc):
    try:
        result = run_certification(body["contract_name"], body["source"])
        (OUTDIR / f"{job_id}.json").write_text(json.dumps({"buyer": buyer, "request": {"contract_name": body["contract_name"]}, "audit": result}))
        cumulative = esc[2] + 1
        expiry = int(time.time()) + 3600
        sig = sign_attestation(buyer, CERTIFY_LISTING_ID, cumulative, expiry)
        tx = market.functions.settle(CERTIFY_LISTING_ID, buyer, cumulative, expiry, sig).build_transaction({
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
        print(f"[certify] job {job_id} done, settled use #{cumulative}", flush=True)
    except Exception as e:
        with JOBS_LOCK: JOBS[job_id] = {"status": "failed", "error": str(e)}
        print(f"[certify] job {job_id} FAILED: {e}", flush=True)


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
        if self.path != "/certify":
            self.send_response(404); self.end_headers(); return
        if self.headers.get("Authorization") != f"Bearer {os.getenv('TAP_SERVICE_TOKEN')}":
            self.send_response(401); self.end_headers(); self.wfile.write(b'{"error":"unauthorized"}'); return
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        body = json.loads(raw)
        buyer = Web3.to_checksum_address(body["buyer"])
        esc = market.functions.escrows(CERTIFY_LISTING_ID, buyer).call()
        if esc[1] <= esc[2]:
            self.send_response(402); self.end_headers(); self.wfile.write(b'{"error":"no unused pack - buy first"}'); return
        job_id = uuid.uuid4().hex[:12]
        with JOBS_LOCK: JOBS[job_id] = {"status": "working"}
        threading.Thread(target=run_job, args=(job_id, body, buyer, esc), daemon=True).start()
        self.send_response(202); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps({"job_id": job_id, "status": "working", "poll": f"/result/{job_id}"}).encode())


if __name__ == "__main__":
    port = 8791
    print(f"[certify] certification service on :{port} | listing {CERTIFY_LISTING_ID}", flush=True)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
