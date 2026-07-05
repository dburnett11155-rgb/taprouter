// dashboard.js — serves the local wallet dashboard and opens the browser.
import { createServer } from "http";
import { readFileSync } from "fs";
import { exec } from "child_process";
import { platform } from "os";

export function launchDashboard(walletPath, port = 4278) {
  const w = JSON.parse(readFileSync(walletPath, "utf8"));
  const html = PAGE.replaceAll("__ADDRESS__", w.smartAccount);
  const srv = createServer((req, res) => {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(html);
  });
  srv.listen(port, "127.0.0.1", () => {
    const url = `http://127.0.0.1:${port}`;
    console.log(`Dashboard: ${url}`);
    const cmd = platform() === "win32" ? `start ${url}` : platform() === "darwin" ? `open ${url}` : `xdg-open ${url}`;
    exec(cmd);
  });
  return srv;
}

const PAGE = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Your Tap Wallet</title>
<style>
  body{font-family:ui-sans-serif,system-ui;background:#0d0f14;color:#e8eaed;margin:0;display:flex;justify-content:center}
  .wrap{max-width:560px;padding:48px 24px;width:100%}
  .kicker{font-size:12px;letter-spacing:3px;color:#4fd1e0;font-weight:600}
  h1{font-size:26px;margin:8px 0 24px}
  .card{background:#12151c;border:1px solid #232936;border-radius:16px;padding:22px;margin-bottom:16px}
  .label{color:#8b939e;font-size:13px;margin-bottom:6px}
  .addr{font-family:ui-monospace,monospace;font-size:14px;word-break:break-all;color:#e8eaed}
  .big{font-size:40px;font-weight:700;color:#4fd1e0}
  button{background:#4fd1e0;color:#0d0f14;border:0;border-radius:10px;padding:11px 18px;font-weight:700;font-size:14px;cursor:pointer;margin-top:10px}
  button.ghost{background:#1a1f29;color:#c9d1d9;border:1px solid #2a3140}
  .ok{color:#5fe0a8}.warn{color:#e0b45f}
  .row{display:flex;gap:10px;flex-wrap:wrap}
  .small{font-size:13px;color:#8b939e;line-height:1.6}
</style></head><body><div class="wrap">
  <div class="kicker">TAP LABS</div>
  <h1>Your assistant's wallet</h1>

  <div class="card">
    <div class="label">Balance</div>
    <div class="big" id="bal">…</div>
    <div class="small" id="balnote">reading from the blockchain…</div>
    <div class="row">
      <button onclick="fund()" id="fundbtn">Add free test money</button>
      <button class="ghost" onclick="load()">Refresh</button>
    </div>
  </div>

  <div class="card">
    <div class="label">Wallet address (this machine)</div>
    <div class="addr" id="addr">__ADDRESS__</div>
    <button class="ghost" onclick="navigator.clipboard.writeText('__ADDRESS__');this.textContent='Copied!'">Copy address</button>
    <div class="small" style="margin-top:10px">This wallet can only spend on TapMarket — enforced by the blockchain. Freeze anytime: <code>npx tapmarket-connect revoke</code>. Withdraw: <code>npx tapmarket-connect withdraw &lt;amount&gt; &lt;address&gt;</code></div>
  </div>

  <div class="card">
    <div class="label">Next step</div>
    <div class="small">Open <b>Claude Desktop</b> (restart it if it was open) and ask: <i>"What specialists can you hire for me?"</i></div>
  </div>

  <div class="small">Receipts for every payment: <a href="https://sepolia.basescan.org/address/__ADDRESS__" style="color:#4fd1e0">view on Basescan</a> · Test mode — no real money · <a href="https://tappayment.io" style="color:#4fd1e0">tappayment.io</a></div>
</div>
<script>
const ADDR="__ADDRESS__", USDC="0x036CbD53842c5426634e7929541eC2318f3dCF7e", RPC="https://sepolia.base.org";
async function load(){
  try{
    const data="0x70a08231000000000000000000000000"+ADDR.slice(2);
    const r=await fetch(RPC,{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({jsonrpc:"2.0",id:1,method:"eth_call",params:[{to:USDC,data},"latest"]})});
    const j=await r.json();
    const v=parseInt(j.result,16)/1e6;
    document.getElementById("bal").textContent="$"+v.toFixed(2);
    document.getElementById("balnote").innerHTML=v>0?'<span class="ok">Funded — your assistant can hire.</span>':'<span class="warn">Empty — tap "Add free test money".</span>';
  }catch(e){document.getElementById("balnote").textContent="couldn't reach the blockchain — refresh to retry";}
}
async function fund(){
  const b=document.getElementById("fundbtn");b.textContent="Adding…";b.disabled=true;
  try{
    const r=await fetch("https://fund.tappayment.io/fund",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({address:ADDR})});
    const j=await r.json();
    b.textContent=j.funded?"Added $1.00!":(j.error||"didn't work");
  }catch(e){b.textContent="didn't work — try again";}
  setTimeout(load,4000);
}
load();setInterval(load,15000);
</script></body></html>`;
