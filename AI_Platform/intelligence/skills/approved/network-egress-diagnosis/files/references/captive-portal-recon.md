# Captive portal / campus network recon (WSL → Windows host)

Answer three questions in order — (1) is there real egress, (2) is this client
authorised, (3) which portal/AAA product sits in front and where does the user
pay the bill. Only then advise on anything.

## 1. Radio and L3 facts (Windows side, called from WSL)

```bash
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
$PS -NoProfile -Command "netsh wlan show interfaces" | tr -d '\r'
$PS -NoProfile -Command "Get-NetRoute -DestinationPrefix 0.0.0.0/0 | ft InterfaceAlias,NextHop,RouteMetric,InterfaceMetric" | tr -d '\r'
$PS -NoProfile -Command "Get-DnsClientServerAddress -InterfaceAlias WLAN -AddressFamily IPv4 | Select -Expand ServerAddresses" | tr -d '\r'
$PS -NoProfile -Command "Get-CimInstance Win32_NetworkAdapterConfiguration | ? {\$_.IPAddress -like '10.*'} | fl DHCPServer,DHCPEnabled,Description" | tr -d '\r'
ip neigh show dev eth1
```

Reads:

- `Authentication : Open` + `Cipher : None` ⇒ auth happens **above** layer 2.
  "Open Wi-Fi" is not "no auth"; never report it as such.
- Gateway MAC `00:00:5e:00:01:01` ⇒ VRRP virtual MAC, i.e. a redundant BRAS
  pair. The gateway IP is virtual and identifies no individual client.
- `DHCPServer == gateway` ⇒ the BRAS hands out leases itself (typical ME60).
- `Get-NetIPConfiguration` prints gateway/DNS as `MSFT_NetRoute(...)` object
  ids — unreadable. Use the two commands above instead.

## 2. Prove auth state, not reachability

```bash
curl -sS -m 10 https://ipinfo.io/json          # IPv4 egress + AS
curl -6 -sS -m 8 -o /dev/null -w '%{http_code}\n' https://www.cloudflare.com/cdn-cgi/trace
```

- Routable campus IP in an education ISP (`AS4538` = CERNET, `AS4134` =
  CHINANET…) ⇒ this client is authorised right now.
- Overseas IP ⇒ a proxy carried the request; the probe proves nothing about the
  campus session. Check `Get-Process | ? ProcessName -match
  'clash|mihomo|verge|v2ray|xray|sing-box'` and Tailscale `ExitNodeID` first.
- AAAA resolving to a global IPv6 address does not mean IPv6 egress exists —
  test `-6` explicitly and expect it to be dead on dorm segments.

Whitelist trap: `generate_204`, `captive.apple.com`, `connectivitycheck.gstatic.com`
returning 204/200 while arbitrary hosts time out = **unauthorised portal**.
Those domains are whitelisted by the portal vendor on purpose. One random site
(`neverssl.com` and friends) timing out proves nothing at all.

## 3. Find the portal from evidence, not scans

Browser history is the cheapest source and the least invasive:

```bash
cp "/mnt/c/Users/<user>/AppData/Local/Google/Chrome/User Data/Default/History" /tmp/ch.db
python3 - <<'EOF'
import sqlite3,re
c=sqlite3.connect('/tmp/ch.db')
pat=re.compile(r'(school-token|portal|srun|eportal|drcom|acip=|nasId=|selfaaa|/api/r/|\d+\.\d+\.\d+\.\d+)',re.I)
for u,v,t in c.execute("select url,visit_count,datetime(last_visit_time/1000000-11644473600,'unixepoch','localtime') from urls"):
    if pat.search(u): print(t,v,u[:170])
EOF
```

Copy the file first — the browser holds a lock on the live DB. Repeat for
`Microsoft/Edge/User Data/Default/History`.

The portal query string is a full description of the enforcement device:

```
http://<portal>/tpl/<tenant>/login.html?acip=172.30.1.223&acname=WHUT-Bras-ME60-A
        &ip=10.78.211.83&nasId=52&userip=10.78.211.83
```

⇒ Huawei ME60 BRAS as NAS (`acname`), per-school template (`/tpl/<tenant>/`),
`/api/r/<nasId>` routing the page per access controller, `/tpl/…/success.html`
for the post-auth page.

Then read the login page as a manifest:

```bash
curl -sS -D- -o page.html "http://<portal>/tpl/<tenant>/login.html?<params>"   # `Server:` header names the product
grep -oE '(src|href)="[^"]+"' page.html | sort -u
```

- `Server: BingoCloud` (and similar) ⇒ portal appliance front-end, BRAS behind.
- `<x>aaa.<school>.edu.cn` / title 「上网管理自服务平台」 ⇒ billing, 套餐, traffic
  and session history live there — that is where a cost question is answered.
- A 「防代理处理方法」 link on the login page ⇒ anti-proxy detection is live.
- CAS host (`tpass`, `/cas`, `service=`) ⇒ unified campus identity, same account
  as the rest of the school's systems.

## 4. Vendor fingerprints

| Signal | Family |
|---|---|
| `/tpl/<tenant>/login.html`, `/api/r/<nasId>`, `BingoCloud` server header | portal appliance + Huawei/H3C BRAS |
| `acname=*Bras-ME60*`, `nasId=`, `userip=` | Huawei ME60 BRAS portal auth |
| `srun_portal_pc`, `ac_id=` | 深澜 Srun |
| `/eportal/`, `eportal.do` | 锐捷 Ruijie ePortal |
| `drcom`, `dr1003`, 城市热点 | Dr.COM |

GitHub landscape: the ecosystem is overwhelmingly **auto-login / keepalive for
an account you already pay for** — ePortal (`CampusNetAutoLogin`-class repos),
Dr.COM (`HFUT-DrCOM`, `drcom-generic`), Srun (`srun_portal` scripts), plus
ESP32 build-ins. That is the legitimate automation to offer. Repos claiming
免认证 / 破解 do MAC cloning, proxy sharing or session replay: name the category,
never wire it up, never reproduce the method.

## 5. What to offer instead of a bypass

- **Keepalive daemon** with their own credentials as a systemd **user** unit,
  alerting the existing chat channel on drop. Campus sessions expire and this
  box loses power overnight, so morning cron jobs fail on a dead link — that is
  usually the real complaint behind "the network doesn't work".
- **Mirror sources** for apt/pip/conda/npm/docker. On a traffic-billed dorm line
  this is the single largest real saving; installs are what burn the quota.
- **Billing audit**: repeated re-auth after drops can be counted as separate
  sessions; verify before paying for a bigger package.
- **Phone hotspot / campus SIM** for occasional laptop use, with hotspot caps
  stated up front.

Refuse the bypass in their terms rather than with a policy recital: enforcement
is account↔MAC↔IP at the BRAS, per-device logs exist, anti-proxy detection is
live, and the exposure is enrolment discipline, not just a fee.
