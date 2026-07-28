// dashboard.js — local control panel: wallet, liquidity, hires, marketplace.
// Runs on 127.0.0.1 only. The wallet is unlocked once at start and held in memory
// for the session so LP actions don't re-prompt; the key never leaves this machine.
import { createServer } from "http";
import { readFileSync, existsSync } from "fs";
import { exec } from "child_process";
import { platform, homedir } from "os";
import { join } from "path";

const USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e";
const TAP_VAULT = "0x1360d65342b1F9543ce2A69e07076efE75657025";
const RPC = "https://sepolia.base.org";

async function rpcCall(to, data) {
  const r = await fetch(RPC, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_call", params: [{ to, data }, "latest"] }) });
  const j = await r.json();
  return j.result;
}

function readHires() {
  try {
    const p = join(homedir(), ".tapmarket", "hires.jsonl");
    if (!existsSync(p)) return [];
    return readFileSync(p, "utf8").trim().split("\n").filter(Boolean)
      .map(l => { try { return JSON.parse(l); } catch { return null; } })
      .filter(Boolean).reverse().slice(0, 25);
  } catch { return []; }
}

async function readRegistry() {
  try {
    const r = await fetch("https://registry.tappayment.io/registry", { signal: AbortSignal.timeout(5000) });
    const j = await r.json();
    return j.specialists || [];
  } catch { return []; }
}


const TAP_MARKET_ADDR = "0xBfd085f192d2246F1BFBe386DF399335dc894f2c";
const TOPIC_SETTLED = "0x827b15754d0688fffb9a637c26c68d038f9e83691e79a263dfda8098da52ad4d";
const AGENT_NAMES = { 1: "Hermes", 2: "Scribe", 4: "Crucible", 5: "Crucible Certify" };

async function rpc(method, params) {
  const r = await fetch(RPC, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }) });
  return (await r.json()).result;
}

// Recent settled hires across ALL agents, paged back within the RPC log-range cap.
async function marketPulse() {
  const latestHex = await rpc("eth_blockNumber", []);
  const latest = parseInt(latestHex, 16);
  const PAGE_SIZE = 2000, PAGES = 5;
  let logs = [];
  for (let i = 0; i < PAGES; i++) {
    const to = latest - i * PAGE_SIZE;
    const from = Math.max(0, to - PAGE_SIZE + 1);
    try {
      const res = await rpc("eth_getLogs", [{ address: TAP_MARKET_ADDR, topics: [TOPIC_SETTLED],
        fromBlock: "0x" + from.toString(16), toBlock: "0x" + to.toString(16) }]);
      if (Array.isArray(res)) logs = logs.concat(res);
    } catch {}
  }
  const hires = logs.map(l => {
    const listingId = parseInt(l.topics[1], 16);
    const buyer = "0x" + l.topics[2].slice(26);
    // data = delta, builderShare, protocolFee, newSettledTotal (each 32 bytes)
    const d = l.data.slice(2);
    const builderShare = parseInt(d.slice(64, 128), 16) / 1e6;
    const protocolFee = parseInt(d.slice(128, 192), 16) / 1e6;
    return { listingId, agent: AGENT_NAMES[listingId] || ("Listing #" + listingId),
             buyer: buyer.slice(0, 6) + "…" + buyer.slice(-4),
             value: +(builderShare + protocolFee).toFixed(4),
             tx: l.transactionHash, block: parseInt(l.blockNumber, 16) };
  }).sort((a, b) => b.block - a.block);
  const volume = hires.reduce((s, h) => s + h.value, 0);
  const byAgent = {};
  hires.forEach(h => { byAgent[h.agent] = byAgent[h.agent] || { hires: 0, volume: 0 };
    byAgent[h.agent].hires++; byAgent[h.agent].volume += h.value; });
  return { hires: hires.slice(0, 15), totalHires: hires.length, volume: +volume.toFixed(4),
           byAgent, windowBlocks: PAGE_SIZE * PAGES };
}

async function vaultStats() {
  const [tl, fees, front] = await Promise.all([
    rpcCall(TAP_VAULT, "0x15770f92"), rpcCall(TAP_VAULT, "0xe4af16a1"), rpcCall(TAP_VAULT, "0xdad5b42b")]);
  return { totalLiquidity: parseInt(tl || "0x0", 16) / 1e6,
           accruedFees: parseInt(fees || "0x0", 16) / 1e6,
           fronted: parseInt(front || "0x0", 16) / 1e6 };
}

export async function launchDashboard(walletPath, port = 4278) {
  const w = JSON.parse(readFileSync(walletPath, "utf8"));
  const addr = w.smartAccount;

  // Unlock once at start — held in memory for this session only.
  let unlocked = null;
  try {
    const { unlockOwnerKey, isOwnerKeyEncrypted } = await import("./wallet-store.js");
    if (isOwnerKeyEncrypted(w)) {
      console.log("Unlock your wallet to enable liquidity actions (or press Enter to run read-only):");
      const key = await unlockOwnerKey(w);
      unlocked = { ...w, ownerKey: key };
      console.log("Wallet unlocked for this session.");
    } else {
      unlocked = w;
    }
  } catch (e) {
    console.log("Running read-only (wallet not unlocked):", String(e).slice(0, 80));
  }

  const html = PAGE.replaceAll("__ADDRESS__", addr);

  const srv = createServer(async (req, res) => {
    const send = (code, obj) => { res.writeHead(code, { "Content-Type": "application/json" }); res.end(JSON.stringify(obj)); };

    if (req.url === "/api/lp-status") {
      try {
        const sharesData = "0xce7c2ac2" + addr.slice(2).padStart(64, "0");
        const feesData = "0x25d2a3f3" + addr.slice(2).padStart(64, "0");
        const [s, f] = await Promise.all([rpcCall(TAP_VAULT, sharesData), rpcCall(TAP_VAULT, feesData)]);
        return send(200, { shares: parseInt(s || "0x0", 16) / 1e6, fees: parseInt(f || "0x0", 16) / 1e6, unlocked: !!unlocked });
      } catch (e) { return send(200, { shares: 0, fees: 0, unlocked: !!unlocked, error: String(e).slice(0, 100) }); }
    }

    if (req.url === "/api/pulse") {
      try { const [m, v] = await Promise.all([marketPulse(), vaultStats()]); return send(200, { ...m, vault: v }); }
      catch (e) { return send(200, { hires: [], totalHires: 0, volume: 0, byAgent: {}, vault: {}, error: String(e).slice(0, 120) }); }
    }
    if (req.url === "/api/hires") return send(200, { hires: readHires() });
    if (req.url === "/api/agents") return send(200, { agents: await readRegistry() });

    if (req.url === "/api/lp-deposit" || req.url === "/api/lp-withdraw") {
      if (!unlocked) return send(400, { error: "wallet locked — restart the dashboard and enter your passphrase" });
      let body = ""; for await (const c of req) body += c;
      let amount = 0;
      try { amount = Math.round(parseFloat(JSON.parse(body).amount) * 1e6); } catch { return send(400, { error: "bad amount" }); }
      if (!amount || amount <= 0) return send(400, { error: "enter an amount greater than zero" });
      try {
        const lib = await import("./init-lib.js");
        const tx = req.url === "/api/lp-deposit"
          ? await lib.lpDeposit(unlocked, amount)
          : await lib.lpWithdraw(unlocked, amount);
        return send(200, { tx });
      } catch (e) { return send(500, { error: String(e.shortMessage || e.message || e).slice(0, 200) }); }
    }

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
<title>TapMarket — your dashboard</title>
<style>
  :root{--ink:#1a1d29;--slate:#5b6473;--mute:#8a92a1;--line:#d7dce5;--lineSoft:#e3e7ee;--panel:#f7f8fb;--accent:#4338ca;--soft:#eef0fd;--ok:#0f9d75}
  *{box-sizing:border-box}
  body{font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;background:#fff;color:var(--ink);margin:0;display:flex;justify-content:center}
  .wrap{max-width:820px;padding:36px 24px 64px;width:100%}
  .brand{display:flex;align-items:center;gap:9px;font-weight:700;font-size:17px;margin-bottom:26px}
  .logo{width:24px;height:24px;border-radius:7px;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;font-size:13px}
  h2{font-size:15px;font-weight:700;margin:0 0 4px;letter-spacing:-.2px}
  .card{border:1px solid var(--line);border-radius:16px;padding:22px;margin-bottom:16px;background:linear-gradient(180deg,#fbfbfe 0%,#fff 60%);box-shadow:0 1px 2px rgba(26,29,41,.04),0 8px 24px -12px rgba(67,56,202,.10)}
  .statgrid{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid var(--lineSoft);margin-top:18px}
  .statcell{padding:16px 18px;border-right:1px solid var(--lineSoft)}
  .statcell:last-child{border-right:none}
  .statlabel{font-size:11.5px;color:var(--slate);letter-spacing:.6px;margin-bottom:6px;font-weight:700}
  .statval{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.5px}
  .livedot{width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 3px rgba(15,157,117,.15);display:inline-block;animation:lp 2s ease-in-out infinite}
  @keyframes lp{0%,100%{opacity:1}50%{opacity:.35}}
  .bartrack{height:4px;border-radius:99px;background:var(--lineSoft);overflow:hidden;margin-top:4px}
  .barfill{height:100%;border-radius:99px;background:var(--accent)}
  .empty{border:1px dashed var(--line);border-radius:10px;padding:16px;color:var(--mute);font-size:13px;text-align:center}
  .feedrow{display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-bottom:1px solid #f3f4f8;font-size:13.5px}
  .feedrow:last-child{border-bottom:none}
  .mono{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;color:var(--mute)}
  .label{color:var(--slate);font-size:12px;font-weight:700;letter-spacing:.6px;margin-bottom:8px;text-transform:uppercase}
  .big{font-size:34px;font-weight:800;letter-spacing:-1px}
  .addr{font-family:ui-monospace,Menlo,monospace;font-size:13px;word-break:break-all;color:var(--slate)}
  button{background:var(--accent);color:#fff;border:0;border-radius:9px;padding:10px 16px;font-weight:600;font-size:14px;cursor:pointer;font-family:inherit}
  button.ghost{background:#fff;color:var(--ink);border:1px solid var(--line)}
  button:disabled{opacity:.55;cursor:default}
  input{border:1px solid var(--line);border-radius:9px;padding:10px 12px;font-size:14px;font-family:inherit;width:120px}
  .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:12px}
  .small{font-size:13px;color:var(--slate);line-height:1.6}
  .muted{font-size:12.5px;color:var(--mute);line-height:1.55}
  .stat{display:flex;justify-content:space-between;align-items:baseline;padding:9px 0;border-bottom:1px solid var(--line)}
  .stat:last-child{border-bottom:none}
  .ok{color:var(--ok);font-weight:600}
  a{color:var(--accent);text-decoration:none}
  .hire{display:flex;justify-content:space-between;gap:10px;padding:10px 0;border-bottom:1px solid var(--line);font-size:13.5px}
  .hire:last-child{border-bottom:none}
  .agent{display:flex;justify-content:space-between;gap:10px;padding:11px 0;border-bottom:1px solid var(--line)}
  .agent:last-child{border-bottom:none}
  .pill{display:inline-block;font-size:11px;font-weight:600;color:var(--accent);background:var(--soft);padding:3px 9px;border-radius:999px}
</style></head><body><div class="wrap">
  <div class="brand"><span class="logo">T</span>TapMarket</div>

  <div class="card">
    <div class="label">YOUR WALLET</div>
    <div class="big" id="bal">…</div>
    <div class="small" id="balnote">reading from the blockchain…</div>
    <div class="row">
      <button onclick="fund()" id="fundbtn">Add test funds</button>
      <button class="ghost" onclick="loadAll()">Refresh</button>
    </div>
    <div class="addr" style="margin-top:14px">__ADDRESS__</div>
    <div class="muted" style="margin-top:8px">This wallet can only spend on TapMarket — enforced by the contract. <a href="https://sepolia.basescan.org/address/__ADDRESS__" target="_blank">View on Basescan</a></div>
  </div>

  <div class="card">
    <div style="display:flex;align-items:center;justify-content:space-between">
      <div style="display:flex;align-items:center;gap:9px"><span class="livedot"></span><span class="label" style="margin:0">MARKETPLACE PULSE</span></div>
      <span class="muted" id="pulsewin">reading chain…</span>
    </div>
    <h2 style="margin-top:10px">What the rail is doing</h2>
    <div class="statgrid">
      <div class="statcell"><div class="statlabel">VOLUME</div><div class="statval" id="pvol">…</div></div>
      <div class="statcell"><div class="statlabel">HIRES</div><div class="statval" id="phires">…</div></div>
      <div class="statcell"><div class="statlabel">VAULT</div><div class="statval" id="pvault">…</div></div>
      <div class="statcell"><div class="statlabel">LP FEES</div><div class="statval ok" id="pfees">…</div></div>
    </div>
    <div class="label" style="margin-top:20px">BY AGENT</div>
    <div id="pagents" class="small">…</div>
    <div class="label" style="margin-top:18px">LIVE FEED</div>
    <div id="pfeed" class="small">…</div>
  </div>

  <div class="card">
    <div class="label">LIQUIDITY</div>
    <h2>Put idle funds to work</h2>
    <div class="small">Commit USDC to the settlement vault and earn a share of fees from real settlement volume.</div>
    <div style="margin-top:14px">
      <div class="stat"><span class="small">Your committed liquidity</span><strong id="lpshares">…</strong></div>
      <div class="stat"><span class="small">Fees earned from volume</span><strong class="ok" id="lpfees">…</strong></div>
    </div>
    <div class="row">
      <input id="lpamt" type="number" step="0.01" min="0" placeholder="0.00">
      <button onclick="lp('deposit')" id="depbtn">Commit</button>
      <button class="ghost" onclick="lp('withdraw')" id="wdbtn">Withdraw</button>
    </div>
    <div class="muted" id="lpnote" style="margin-top:10px">Your capital stays yours — it's credited to your address in the vault contract and you can withdraw anytime. Tap never holds your funds.</div>
  </div>

  <div class="card">
    <div class="label">RECENT HIRES</div>
    <div id="hires" class="small">loading…</div>
  </div>

  <div class="card">
    <div class="label">MARKETPLACE</div>
    <div id="agents" class="small">loading…</div>
    <div class="muted" style="margin-top:12px">Hire from your AI assistant: <i>"What specialists can you hire?"</i></div>
  </div>

  <div class="muted">Test mode on Base Sepolia · <a href="https://tappayment.io" target="_blank">tappayment.io</a></div>
</div>
<script>
const ADDR="__ADDRESS__", USDC="0x036CbD53842c5426634e7929541eC2318f3dCF7e", RPC="https://sepolia.base.org";
const $=id=>document.getElementById(id);
async function loadBal(){
  try{
    const data="0x70a08231000000000000000000000000"+ADDR.slice(2);
    const r=await fetch(RPC,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({jsonrpc:"2.0",id:1,method:"eth_call",params:[{to:USDC,data},"latest"]})});
    const v=parseInt((await r.json()).result,16)/1e6;
    $("bal").textContent="$"+v.toFixed(2);
    $("balnote").innerHTML=v>0?'<span class="ok">Funded — ready to hire.</span>':'Empty — add test funds to get started.';
  }catch(e){$("balnote").textContent="couldn't reach the blockchain — refresh to retry";}
}
async function loadLp(){
  try{
    const j=await (await fetch("/api/lp-status")).json();
    $("lpshares").textContent="$"+(j.shares||0).toFixed(2);
    $("lpfees").textContent="$"+(j.fees||0).toFixed(2);
    if(!j.unlocked){$("depbtn").disabled=true;$("wdbtn").disabled=true;$("lpnote").textContent="Wallet locked — restart the dashboard and enter your passphrase to commit or withdraw.";}
  }catch(e){$("lpshares").textContent="—";$("lpfees").textContent="—";}
}
async function loadHires(){
  try{
    const j=await (await fetch("/api/hires")).json();
    if(!j.hires.length){$("hires").textContent="No hires yet. Ask your assistant to hire a specialist.";return;}
    $("hires").innerHTML=j.hires.map(h=>'<div class="hire"><span><strong>'+(h.specialist||"?")+'</strong> <span class="muted">'+(h.ts||"").slice(0,10)+'</span></span><span>'+(h.charge||"")+(h.settleTx?' · <a href="https://sepolia.basescan.org/tx/'+h.settleTx+'" target="_blank">receipt</a>':'')+'</span></div>').join("");
  }catch(e){$("hires").textContent="couldn't load hires";}
}
async function loadAgents(){
  try{
    const j=await (await fetch("/api/agents")).json();
    if(!j.agents.length){$("agents").textContent="couldn't reach the registry";return;}
    const NICE={hermes:"Hermes",scribe:"Scribe",crucible:"Crucible","crucible-certify":"Crucible Certify"};
    $("agents").innerHTML=j.agents.map(a=>'<div class="agent"><span><strong>'+(NICE[a.id]||a.id.charAt(0).toUpperCase()+a.id.slice(1))+'</strong><br><span class="muted">'+(a.description||"").slice(0,90)+'…</span></span><span class="pill">'+(a.pricePerUse||"")+'</span></div>').join("");
  }catch(e){$("agents").textContent="couldn't load marketplace";}
}
async function lp(kind){
  const amt=$("lpamt").value;
  if(!amt||parseFloat(amt)<=0){$("lpnote").textContent="Enter an amount first.";return;}
  const b=kind==="deposit"?$("depbtn"):$("wdbtn");
  const old=b.textContent;b.textContent="Working…";b.disabled=true;
  try{
    const r=await fetch("/api/lp-"+kind,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({amount:amt})});
    const j=await r.json();
    if(j.tx){$("lpnote").innerHTML='Done — <a href="https://sepolia.basescan.org/tx/'+j.tx+'" target="_blank">view receipt</a>';$("lpamt").value="";}
    else $("lpnote").textContent=j.error||"didn't work";
  }catch(e){$("lpnote").textContent="didn't work — try again";}
  b.textContent=old;b.disabled=false;
  setTimeout(loadAll,4000);
}
async function fund(){
  const b=$("fundbtn");b.textContent="Adding…";b.disabled=true;
  try{
    const j=await (await fetch("https://fund.tappayment.io/fund",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({address:ADDR})})).json();
    b.textContent=j.funded?"Added $1.00":(j.error||"didn't work");
  }catch(e){b.textContent="didn't work";}
  setTimeout(()=>{b.textContent="Add test funds";b.disabled=false;loadAll();},4000);
}
async function loadPulse(){
  try{
    const j=await (await fetch("/api/pulse")).json();
    $("pvol").textContent="$"+(j.volume||0).toFixed(2);
    $("phires").textContent=j.totalHires||0;
    $("pvault").textContent="$"+((j.vault&&j.vault.totalLiquidity)||0).toFixed(2);
    $("pfees").textContent="$"+((j.vault&&j.vault.accruedFees)||0).toFixed(4);
    $("pulsewin").textContent="Recent activity across all agents (last ~"+(j.windowBlocks||0).toLocaleString()+" blocks).";
    const ba=j.byAgent||{};
    const keys=Object.keys(ba);
    const maxv=Math.max(1,...keys.map(k=>ba[k].volume));
    $("pagents").innerHTML=keys.length?keys.map(k=>'<div style="margin-bottom:10px"><div style="display:flex;justify-content:space-between;font-size:13.5px"><span>'+k+'</span><span class="muted">'+ba[k].hires+' hires · $'+ba[k].volume.toFixed(2)+'</span></div><div class="bartrack"><div class="barfill" style="width:'+Math.round(ba[k].volume/maxv*100)+'%"></div></div></div>').join(""):'<div class="empty">No settled hires in this window — hire an agent and it lands here.</div>';
    $("pfeed").innerHTML=(j.hires&&j.hires.length)?j.hires.map(h=>'<div class="feedrow"><span style="display:flex;align-items:center;gap:9px"><span style="width:5px;height:5px;border-radius:50%;background:var(--accent)"></span><strong>'+h.agent+'</strong> <span class="mono">'+h.buyer+'</span></span><span style="font-variant-numeric:tabular-nums">$'+h.value.toFixed(2)+' · <a href="https://sepolia.basescan.org/tx/'+h.tx+'" target="_blank">tx</a></span></div>').join(""):'<div class="empty">Nothing settled in this window. Hires appear here the moment they land.</div>';
  }catch(e){$("pulsewin").textContent="couldn't read the chain — refresh to retry";}
}
function loadAll(){loadBal();loadLp();loadHires();loadAgents();loadPulse();}
loadAll();setInterval(loadBal,15000);
</script></body></html>`;
