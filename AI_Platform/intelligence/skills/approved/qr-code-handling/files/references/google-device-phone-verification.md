# Google `devicephoneverification` QR (account creation / sign-in)

Observed directly on this box:

- Payload: `https://accounts.google.com/devicephoneverification/begin?hl=en&flow=browser&plt=<long token>&dsh=S-<id>:<epochms>`
- `begin` 302s to `.../devicephoneverification/initiate?...` with the same `plt`.
- The static DOM carries only `Verify your phone` + a `Loading` state: no
  account, no number, no instructions.

## Roles

- **Desktop browser**: shows the QR and polls for the result; the `plt` token is
  bound to *that* in-progress session.
- **Phone**: opens the QR URL and acts as the verifying device. Google expects a
  device it recognises as a phone (Google app / Android / carrier SIM). The phone
  ends up bound in the new account's trust chain with its first-login IP.

## Why an agent browser must not complete it

- A Linux Chrome behind a proxy is not the device class being asked for; the page
  most plausibly never offers a usable confirm affordance (judgement — the page
  did not say).
- If it did, the account's verifying device and first IP would become an agent's
  proxy egress. New Google accounts verified from flagged proxy ranges are
  routinely disabled on first sign-in — the user gets a dead account while
  believing verification succeeded.
- Whoever scans it has, functionally, authority to bind the account. Treat the
  token like a password: don't forward it, don't paste it into other services,
  don't leave it in a screenshot.

## What to tell the user instead

1. Name it: "这是谷歌给你这次注册会话发的一次性手机验证令牌，谁扫谁就是代你验证的那台设备".
2. Give the phone egress from a machine that already has it (LAN proxy, hotspot,
   VPN on the phone). Verify the config and the Windows-side listener before
   instructing them, and be explicit that only the phone opening
   `generate_204` proves the peer path — a WSL-side curl to the host's LAN IP
   tests the guest against itself under mirrored networking
   (`network-egress-diagnosis` Step 3).
3. Offer `Try another way` on the signup page (email verification) as the
   no-network fallback.
