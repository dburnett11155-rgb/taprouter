# Incident Runbook

## Auth enforcement (deployed 2026-07-10)
Hermes + Scribe run with TAP_AUTH_ENFORCE=1 via systemd drop-ins at
/etc/systemd/system/{hermes,scribe}.service.d/enforce-auth.conf

Rollback to observe mode (if a legitimate buyer is being 401'd):
  sudo rm /etc/systemd/system/hermes.service.d/enforce-auth.conf
  sudo systemctl daemon-reload && sudo systemctl restart hermes
(same for scribe). Diagnose after availability is restored, not before.

## Consumer reports "could not connect to tapmarket" after a release
1. npm pack tapmarket-connect@<version> and diff the file list against mcp-server/
   (the 0.1.10 incident: wallet-store.js missing from the files whitelist)
2. Laptop log: %APPDATA%\Claude\logs\mcp-server-tapmarket.log — MODULE_NOT_FOUND
   means broken tarball; killed at exactly 60s means cold-start timeout (relaunch);
   execution-policy error: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
3. Broken release: bump + fix + publish (prepublishOnly guard checks wallet-store.js);
   npm deprecate the broken version.

## Lost wallet passphrase
No recovery by design. Session key still spends within policy: create a fresh
wallet, refund unused packs to it. The orphaned smart account's remaining
balance is recoverable only if the passphrase resurfaces.
