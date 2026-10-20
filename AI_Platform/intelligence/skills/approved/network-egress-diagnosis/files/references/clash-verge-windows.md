# Clash Verge (Windows) as seen from WSL

Everything here is checked by reading files / Windows-side commands, not by
trusting the GUI state the user reports.

## Where the state lives

`%APPDATA%/io.github.clash-verge-rev.clash-verge-rev/` → from WSL
`/mnt/c/Users/<WinUser>/AppData/Roaming/io.github.clash-verge-rev.clash-verge-rev/`

| File | Keys worth grepping |
|---|---|
| `clash-verge.yaml` | `mixed-port` (usually 7897), `allow-lan`, `external-controller`, `secret`, `bind-address` |
| `verge.yaml` | `enable_tun_mode`, `system-proxy`/`system_proxy_bypass`, `tun_tray_icon` |
| `logs/latest.log` | app-level events only (subscription refresh, system-proxy guard) |
| `profiles.yaml`, `profiles/` | subscription list and cached configs |

Reading via `search_files` with `allow-lan|mixed-port|external-controller` is
faster than dumping the whole yaml (which contains node credentials — never
print it wholesale into the transcript).

## Things that look broken but aren't

- `external-controller: ''` + `external-controller-pipe: \\.\pipe\verge-mihomo-...`
  ⇒ the control API is a **Windows named pipe**, so there is no `http://127.0.0.1:9090`
  to query from WSL. Verify with `Test-NetConnection` and the client's own UI/logs
  instead of trying `curl http://<controller>/connections`.
- `System proxy is disabled` in the log while the browser still reaches the
  internet ⇒ the user routes through a browser proxy extension pointing at the
  loopback port; `allow-lan` and the mixed port are unaffected.
- Subscription refresh logging `404` means nodes are running from cache and will
  eventually go stale. Report it once as a separate finding; don't fold it into
  the task at hand.
- `Get-NetTCPConnection -State Listen` showing `::` for the port means all
  interfaces, not just loopback — so Allow-LAN is already doing its job.

## Firewall

```powershell
Get-NetFirewallApplicationFilter | Where-Object { $_.Program -like '*clash*' } |
  ForEach-Object { $x = $_ | Get-NetFirewallRule; '{0} | {1} | {2} | {3}' -f $x.DisplayName, $x.Direction, $x.Action, $x.Enabled }
Get-NetFirewallProfile | Select-Object Name,Enabled,DefaultInboundAction
```

Rule names to expect: `verge-mihomo`, `Clash Verge`, `Clash Verge Service core
(verge-mihomo.exe)`. `DefaultInboundAction: NotConfigured` on all three profiles
means the profile-level default is block, so a per-app Allow rule is what makes
the port usable.

## Lending it to a phone

Phone Wi-Fi (same SSID) → 高级 → 代理「手动」→ 主机 = Windows LAN IP, 端口 =
`mixed-port`. If that SSID is campus/dorm, client isolation may block it; then
use Windows Mobile Hotspot and point the phone at `192.168.137.1:<mixed-port>`.
Only the phone's own `https://www.google.com/generate_204` settles it — a WSL-side
curl to the LAN IP tests the guest against itself under mirrored networking.
