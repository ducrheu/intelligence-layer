# Exposing a local runtime: routes, and the protocol facts that constrain them

Companion to §11. Everything here fronts a service that stays bound to `127.0.0.1`; none of it
rebinds one.

## Route comparison

| Route | Auth strength | Attack surface | Cost to set up | Client offline |
|---|---|---|---|---|
| Mesh VPN node share (Tailscale/WireGuard) | device identity + network ACL, deny-by-default once policies are written | only the shared machine; a shared node is quarantined by default (inbound only) and carries no tags/groups/subnets | low; the recipient needs the client and an account | good: recovery does not depend on a public entrypoint |
| SSH tunnel (`ssh -N -L 8765:127.0.0.1:8765 …`) | strong (host key + public key) | needs SSH reachability to this box | one command | medium: reconnect is manual |
| Public tunnel (Cloudflare Tunnel / ngrok) | "whoever knows the URL" unless an identity layer is stacked on it | the endpoint is genuinely public; a misconfiguration is a bare service | medium; cloudflared dials out, so inbound can stay closed | good |
| mTLS | strong; a token can be bound to the certificate (RFC 8705) | you own issuance, revocation and rotation | medium-high (PKI) | same as HTTP |
| Reverse proxy + OAuth | strong, user-level identity, one front door | a bypassable proxy is the hole; a wrong JWT check is no auth | medium-high | good, but session expiry interrupts long tasks |

**A mesh VPN's real trap:** on Tailscale, if you write no `acls` section the default is *allow
all*, not deny — write the policy explicitly. Node sharing is the narrower tool for a single
recipient and strips their view to just that machine.

## Pick by the client's answers

- Third party, arbitrary network, willing to install a client → **mesh VPN node share**, then
  serve the app on the tailnet with the target still `http://127.0.0.1`.
- Third party, arbitrary network, will install nothing → **public tunnel plus an identity layer**
  (an access-control fronting, or service tokens); this is the only route where a stranger's
  browser is the client, so the identity layer is mandatory, not optional.
- You, on another of your own devices → mesh VPN, or an SSH tunnel if you only need it now.
- Must keep working while the host is off → no thin client; it has to be an isomorphic runtime on
  an always-on host, with only the knowledge layer shared.

## Free routes, and the facts that decide between them

When there is no domain and no budget, the mesh-VPN node share is the whole answer — and the
specifics that make it usable are all quoted from vendor documentation, not inferred:

- **Sharing is available on all plans**, and the recipient does **not** need a Tailscale account
  with the same email — they accept a single-use invite link (unused links expire after 30 days).
- **A shared machine is quarantined by default**: it *"can receive incoming connections … but cannot
  start connections"*, and sharing strips tags, groups and subnet routes from the recipient's view.
  This is the property that makes it the narrow tool rather than "let them into my tailnet".
- **`tailscale serve` proxies only `http://127.0.0.1`** — *"Note that only http://127.0.0.1 is
  supported for proxies."* That single restriction is why the loopback bind survives exposure and why
  this pairs cleanly with the never-rebind rule above. A public tunnel provider, by contrast, asks
  for the target of your choice but requires a domain on their platform to publish a named app;
  their no-domain "quick" tunnels are documented as **testing and development only**, with no SLA.
- **Do not use Funnel for a third party.** Vendor docs say it *"doesn't work with other Tailscale
  features like … access controls"*, that Funnel traffic (unlike Serve) **carries no identity
  headers**, and that it is limited to ports 443/8443/10000. That combination hands "who may connect"
  entirely back to the application, which is the opposite of what this route is chosen for.
- **No transport removes "the host must be on".** Serve/Funnel, node sharing and the tunnel providers
  all state it as a shared precondition: reachable only while the device is online and the service is
  running. There is no built-in queueing or offline fallback, so a nightly power-down is an
  availability statement to the user — never a thing to engineer around with a thin client.
- **A tunnel's own health indicator is not a service check.** Cloudflare documents that
  `Healthy` *"confirms only that cloudflared connects to Cloudflare … does not test the route's
  service or the local origin"*; the same over-claim applies to any provider dashboard. If the
  operator needs to know the service is up, that check has to run locally.

## Protocol facts that change the design

A2A, v1.0 (published 2026-03-12). The normative artefact is `spec/a2a.proto`; the website JSON is a
build product. Agent Card is mandatory and its well-known URI is
`/.well-known/agent-card.json`; servers MUST provide it, and it SHOULD NOT carry internal
implementation details. Clients MUST send an `A2A-Version` header on every request. Long tasks have
three delivery mechanisms — polling (the documented choice when the client sits behind a
restrictive firewall), SSE streaming (`SubscribeToTask` can re-attach after a disconnect), and
push-notification webhooks, which require the client to be reachable *inbound* and oblige the
server to validate the webhook URL against SSRF (private ranges named in the spec). Production
MUST encrypt transport. **Authorization is explicitly left to the implementation**, and the
enterprise documentation states the payload carries no user/client identity — identity is
established at the HTTP layer, which is why one peer token per machine is the shape the protocol
implies rather than a convention.
`https://a2a-protocol.org/latest/specification` · `https://a2a-protocol.org/latest/topics/enterprise-ready/` ·
`https://a2a-protocol.org/latest/topics/streaming-and-async/` · `https://github.com/a2aproject/A2A/releases/tag/v1.0.0`

MCP, revision 2026-07-28, was a breaking rewrite: protocol-level sessions and `Mcp-Session-Id` are
gone, `initialize` is gone (`server/discover` is mandatory instead), and SSE resumability/
re-delivery was removed — so "reconnect and replay missed events" is no longer a protocol
responsibility, and most advice written before this revision is wrong. Two standard transports
remain: `stdio` and Streamable HTTP (HTTP+SSE is deprecated). Streamable HTTP servers MUST check
the `Origin` header against DNS rebinding, and locally-run servers SHOULD bind `127.0.0.1` only —
**a stdio server (what this install runs) is therefore already the conservative choice**, and the
authorization chapter is normative down to token audience (resource server per RFC 9728, RFC 8707
resource indicators, never pass a client token upstream), which is a far stricter posture than
A2A's. Do not port one protocol's authorization rules onto the other.
`https://modelcontextprotocol.io/specification/2026-07-28/changelog` ·
`https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http` ·
`https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization` ·
`https://modelcontextprotocol.io/specification/2026-07-28/basic/security_best_practices`

## Facts about this box to re-verify before claiming anything is remote-usable

- `ss -tlnp` is the check. Last measured, every application port was `127.0.0.1`; the only
  non-loopback listener was the WSL DNS stub. "Another machine can already reach it" is almost
  always false here.
- An agent card that answers `200` without a token is public by default — the check for whether
  a surface is protected, not evidence that the runtime is ready for visitors.
- The KB gateway's downstream is loopback too, so the shared store is a *same-machine* service,
  not a cross-machine one, and `/mnt/d` is the same machine's Windows side rather than a network
  path.
- A git remote is not a backup for the runtime state: only the tracked artifact tree is pushed,
  while audit/event/token files live outside it in the state directory.

## Standing it up: the app-side half

The route table chooses the transport. Fronting an *agent runtime* has an ordering rule of its own,
because the gate is switched on by the URL rather than by the tunnel.

- **Order: credentials → `public_url` → tunnel.** Declaring a non-loopback `public_url` is what
  engages the dashboard auth gate, and the runtime then **fails closed at startup** when no auth
  provider is configured. So: write the provider's credentials into that profile's `.env` first
  (`USERNAME` / `PASSWORD` or `PASSWORD_HASH` / `SECRET` — the `SECRET` is the session-signing key),
  then set `public_url`, then open the tunnel. A tunnel opened first (or in the same breath) leaves
  the backend answering with the owner's authority for the length of that window. Reverse the order
  and the failure mode is loud and confusing: the service refuses to start at all.
- **`public_url` must be the exact `Host` the browser sends** — it is matched verbatim (also as a
  WebSocket `Origin`), so a wrong MagicDNS name produces rejected requests, not a helpful error.
- **A loopback session token is deliberately not a remote credential.** The documented reason is
  that a non-loopback `public_url` "prevents the local SPA session token from becoming a remote
  authentication mechanism". Tell the operator to expect a **sign-in** (username/password or OAuth),
  not a token to paste — and to set the signing secret, or every restart logs the guest out.
- **Probe the gate state, not the config.** `curl -s http://127.0.0.1:<port>/api/status` reports
  `auth_required` and `auth_providers`; acceptance is `auth_required=true` with the provider listed.
  Measured on an unconfigured backend: `auth_required=false, providers=[]` — that is the state in
  which the port is open to anyone who can reach it, so read it *before* exposing.
- **No `trusted_proxies` entry is needed when the terminator is on loopback** (loopback proxies are
  trusted automatically); only a terminator in another host or container has to be listed.

### Which server process to front, and what "working" looks like

- **`serve` and `dashboard` are two surfaces sharing one server — pick by client, before exposing.**
  `serve` is the headless backend the desktop app connects to: it sets `headless_backend=True` and
  exports `HERMES_SERVE_HEADLESS=1`, which makes `mount_spa()` disable the web UI *even when a build
  exists on disk*. `dashboard` serves the same JSON-RPC/WS API **plus** the UI. So the desktop client
  works against either, a browser works only against `dashboard`, and one process on one port is
  enough for both. For a unit: `hermes dashboard --host 127.0.0.1 --port <p> --no-open --skip-build`.
  `--skip-build` covers the **web** assets only: the chat page additionally runs the bundled TUI, so a
  tenant on a read-only code tree must have that bundle pinned prebuilt or the page reports *Chat
  unavailable* and the journal shows a permission error inside the app tree — see
  `references/tenant-isolation.md` → "A read-only code tree breaks everything that builds on demand".
- **A JSON body where an HTML page was expected is the tell.** Wrong surface, not a broken gate:
  the browser reaches the login, authenticates, and then gets
  `{"error":"Headless backend (hermes serve): web UI disabled — use \`hermes dashboard\` for the
  browser UI."}` with HTTP 200 — nothing in the tunnel or the auth config is at fault, and no amount
  of re-checking `tailscale serve status` will show it.
- **Probe the surface, not the config, to declare the entry path done.** Unauthenticated `/` must be
  a `302` to `/login?next=%2F`; `/login` must return `200` with a sign-in page carrying a password
  field; `/api/auth/me` must be `401`; `/api/status` must report the provider. Run these with the
  public `Host` header too (`curl -H "Host: <public_url host>" http://127.0.0.1:<port>/...`) — the
  auth gate is engaged by `public_url`, so the loopback request is already gated, and this checks the
  host match without needing the guest's machine.
- **The credentials in a profile's `.env` are loaded by a standalone service** — verified on a unit
  with no `EnvironmentFile=`, where the gate engaged and `/api/status` listed the provider. No unit
  edit is needed for the password provider; do not add an `EnvironmentFile` "to be safe" and then
  believe it was what made the gate work.
- **The first `serve --https` has a minute-long TLS gap that looks like a failed step.** The
  certificate is provisioned on demand via ACME DNS-01 (it writes a `_acme-challenge` record first),
  so between the `serve` command and the certificate landing every request fails and the operator
  reads it as "step 4 failed". Check `journalctl -u tailscaled` for
  `health(warnable=tls-cert-pending): error: Fetching TLS certificate via ACME` followed by
  `got cert` — then tell them to retry, not to re-edit anything. The certificate is cached, so later
  restarts of the same name are immediate, and `tailscale status --json` reporting `CertDomains:
  null` before the first `serve` is expected rather than a misconfiguration.

### WSL specifics when the service lives inside WSL2

- **Run the mesh client inside WSL *or* on Windows — never both.** Vendor docs: traffic from WSL over
  the Windows host's Tailscale "will not work", because the packets cannot nest; the WSL interface
  MTU (1280) is also below what the daemon wants and is raised only when it detects WSL. If it later
  gets installed on the Windows side as well, the WSL copy has to come out.
- **`tailscale serve --https` requires HTTPS certificates enabled for the tailnet** in the admin
  console before it will mint one. The tell that it is still off: `tailscale status --json` reports
  `CertDomains: null`.
- **Hand the operator a sudo-free CLI**: `sudo tailscale set --operator=$USER`, otherwise every
  `serve` invocation needs root.
- **Identify the node by tailnet IP when sharing it.** A WSL node commonly inherits the Windows
  hostname and appears in the machine list as a duplicate or `-1` entry.
- `tailscale serve status` reporting **"No serve config"** is the honest state after a successful
  install + login: installing, logging in, and exposing are three separate steps, and the first two
  are not evidence of the third.
