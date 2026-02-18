# ARCHIVAL RESEARCH NOTE

This guide is preserved as historical setup research and is not the canonical runtime spec.

For current source-of-truth operations, use:
- `README.md`
- `openclaw/README.md`
- `docs/cj-jack-repo-access.md`

Last archival review: February 18, 2026.

# OpenClaw Secure Setup Guide (macOS 15.6.1 • Apple Silicon / M4)

This is a **step‑by‑step, handheld** checklist for installing OpenClaw on your **MacBook Pro (Apple M4, 32 GB, macOS 15.6.1 / 24G90)** and running it in the **safest practical way** for high‑risk automation (agents + external websites/APIs + your invoicing app).

> **Important reality check:** you can’t make an agent system “100% secure.” What you *can* do is **defense‑in‑depth**: reduce blast radius, minimize permissions, isolate untrusted code, and make secret leakage difficult and detectable.

---

## What you’re trying to protect

You called out the right risks. In your scenario, assume an attacker might try to:

- **Prompt‑inject** your agent via web pages, docs, or messages (“do X now, run this command…”).
- Ship a **malicious skill** (supply chain) that exfiltrates secrets, runs commands, or downloads payloads.
- Exploit **excessive agency** (the agent has too much power: shell, filesystem, browser sessions, tokens).
- Steal **API keys / cookies / session tokens** from logs, transcripts, env vars, or browser profiles.
- Abuse your invoicing workflow (spoof paid status, trigger spam notifications, enumerate creators, etc.).

Your setup should assume: **untrusted input will eventually reach the agent**.

---

## Two non‑negotiables (read this once)

1. **Legal / ToS boundary:** If a platform (e.g., OnlyFans) forbids scraping or automation, do not bypass those restrictions. Use official APIs, written permission, or a compliant integration. This isn’t just “ethics”; it’s also a security control (scrapers often require risky workarounds).
2. **Secrets never go into prompts:** Never paste API keys, cookies, tokens, or credentials into an agent chat. Treat agent transcripts/logs as potentially leakable.

---

## Quick overview of the safest architecture

**Best practice** is to split your work into 3 separate agents and isolate them:

1. **Invoice Monitor Agent (low risk):**
   - Talks only to **your own** invoicing backend via a narrow internal API.
   - No arbitrary browsing. No shell execution. No file system writes.

2. **Notification Agent (medium risk):**
   - Only sends messages (email/Slack/DM) based on structured events.
   - No browsing. No shell. Minimal secrets.

3. **External Data Agent (highest risk — “OnlyFans/API/scraping” bucket):**
   - Runs **always sandboxed**.
   - Does **not** hold long‑lived secrets.
   - Calls your **broker service** (you control it) using short‑lived tokens.

This reduces the chance that one compromised agent leads to full compromise.

---

# Step‑by‑step setup

## Step 1 — Choose your isolation model (pick ONE)

### Option A (recommended): Run OpenClaw in a disposable macOS VM
This is the cleanest blast‑radius boundary: if anything feels off, you wipe the VM.

**Checklist (VM hardening):**
- Create a new macOS VM using a reputable virtualization tool that supports Apple Silicon.
- In VM settings:
  - **Disable shared clipboard** (or keep it off until needed).
  - **Disable shared folders**.
  - **Disable “shared applications”** / host integration features you don’t need.
  - Use **NAT networking** (not bridged), so the VM isn’t a first‑class device on your LAN.
- Create a **fresh Apple ID** (or no Apple ID) inside the VM—avoid linking personal iCloud.

✅ If you can do Option A, do it. Everything below applies inside the VM.

---

### Option B: Use a dedicated macOS user account on your Mac (acceptable)
If you won’t use a VM, at minimum isolate OpenClaw into a **separate, standard (non‑admin)** user account.

**Do this:**
1. System Settings → **Users & Groups** → Add User
2. Create: `openclaw` (Standard user, not Admin)
3. Log into that user for all OpenClaw activity.

**Rules:**
- Do not sign into personal accounts in this user profile.
- Store OpenClaw workspaces **only** in this user’s home folder.

---

## Step 2 — macOS security baseline (do these first)

On the machine (or VM) you’ll run OpenClaw on:

1. **Update macOS**  
   - System Settings → General → Software Update → install updates.

2. **Turn on FileVault** (laptop theft protection)  
   - System Settings → Privacy & Security → FileVault → Turn On.

3. **Turn on the macOS firewall**  
   - System Settings → Network → Firewall → Turn On.

4. **Keep Gatekeeper protections on**
   - Don’t bypass “unidentified developer” warnings.
   - If anything tells you to run `xattr -dr com.apple.quarantine …` or disable Gatekeeper: **stop**.

✅ Goal: the OS keeps unknown apps from running and reduces network exposure.

---

## Step 3 — Create a clean workspace + lock down permissions

In Terminal (inside the VM or the dedicated `openclaw` user):

```bash
mkdir -p ~/OpenClaw/{workspaces,downloads,backups}
chmod 700 ~/OpenClaw
```

**Why:** if anything leaks, you want it confined to a small directory tree.

---

## Step 4 — Install Xcode Command Line Tools (prereq)

```bash
xcode-select --install
```

If it says they’re already installed, that’s fine.

---

## Step 5 — Install Homebrew (inspect‑then‑run style)

### Download the official installer script to a file first
```bash
cd ~/OpenClaw/downloads
curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o brew-install.sh
less brew-install.sh
```

- Scroll through it (you’re looking for anything obviously suspicious or unrelated).
- Then run it:

```bash
/bin/bash brew-install.sh
```

After install, follow the on‑screen instructions to add brew to your PATH (Homebrew prints the exact commands).

---

## Step 6 — Install OpenClaw (App + CLI) via Homebrew

```bash
brew update
brew install --cask openclaw
brew install openclaw-cli
```

✅ This should place the app in `/Applications/OpenClaw.app`.

---

## Step 7 — Verify the app is signed/notarized (don’t skip)

Run:

```bash
spctl --assess --type execute --verbose /Applications/OpenClaw.app
codesign -dv --verbose=4 /Applications/OpenClaw.app 2>&1 | head -n 40
```

**What you want to see:**
- `spctl` should report “accepted”.
- `codesign` should show a valid signature.

🚫 If macOS asks you to override security protections or the signature check fails, **stop** and reinstall from a known-good source.

---

## Step 8 — First launch: deny permissions by default

1. Open **OpenClaw.app**.
2. macOS may request permissions like:
   - Accessibility
   - Screen Recording
   - Files and Folders
   - Camera/Microphone
3. **Deny everything at first**.
4. Only grant a permission later when:
   - You understand why it’s needed
   - You are actively using that feature

✅ Least‑privilege is your friend.

---

## Step 9 — Run OpenClaw’s security audit immediately

In Terminal:

```bash
openclaw security audit
openclaw security audit --deep
openclaw security audit --fix
openclaw security audit
```

**If the audit flags anything about:**
- public network exposure
- missing auth
- elevated allowlists
- unsafe filesystem permissions  
…treat that as a **blocker** until resolved.

---

## Step 10 — Lock down the Gateway and local services

Your goal: **the Gateway/control surfaces must not be reachable from the network**.

### 10.1 Confirm OpenClaw is only listening on localhost
Run:

```bash
lsof -nP -iTCP -sTCP:LISTEN | grep -i openclaw || true
```

**What you want:**
- Services bound to `127.0.0.1` / `localhost` only.

If you see a service bound to `0.0.0.0` or your LAN IP:
- Fix config to bind to loopback (localhost only)
- Re-run `openclaw security audit`

### 10.2 macOS Firewall sanity check
System Settings → Network → Firewall:
- Ensure OpenClaw is **not** allowed to accept incoming connections unless you specifically need it.

✅ Your “control plane” should not be internet-facing.

---

## Step 11 — Enable sandboxing (highly recommended for your use case)

Sandboxing reduces blast radius when an agent runs tools or interacts with untrusted content.

### 11.1 Install a container runtime (Docker Desktop is simplest)
Option 1 (via Homebrew):
```bash
brew install --cask docker
```

Open Docker once so it finishes setup, then verify:

```bash
docker info
```

If `docker info` works, you’re good.

### 11.2 Turn sandboxing ON and verify it’s actually on
OpenClaw supports sandbox modes (commonly: `off`, `non-main`, `all`).

**Set sandboxing to the most restrictive option that still works (`all`) for any agent that touches the open internet.**

Then run:

```bash
openclaw sandbox explain
openclaw security audit --deep
```

🚫 **Critical footgun:** if sandboxing is off, some “sandbox” labels may still execute on the host. Do not assume you’re sandboxed—verify.

---

## Step 12 — Secrets: prevent API key leakage (the safest pattern)

Your requirement (“no data or API keys will ever be leaked”) is only *approachable* if the agent **never sees long‑lived secrets**.

### 12.1 The safest approach: a backend “broker” service you control
Instead of giving OpenClaw your OnlyFans/API secrets directly:

- Store real secrets on a server/service you control (or a managed secret store).
- Expose a tiny internal API like:
  - `POST /external-data/fetch` (whitelisted actions only)
  - `GET /invoices/status` (your own app)
- Give the agent a **short‑lived token** that:
  - expires quickly
  - has narrow scopes (only the endpoints it needs)
  - can be revoked instantly

**Why this is safer:**
- Even if the agent is prompt‑injected, it can’t dump a long‑lived key.
- You can log, rate-limit, and block suspicious calls at the broker.

### 12.2 If you must use local secrets (not ideal)
If you absolutely must store secrets locally:
- Use **separate keys** for this environment (never reuse your “master” keys).
- Use keys with the **minimum scope**.
- Rotate often.

Also:
- Keep `~/.openclaw` restricted:
  ```bash
  chmod 700 ~/.openclaw || true
  chmod 600 ~/.openclaw/openclaw.json 2>/dev/null || true
  ```
- Ensure log redaction is enabled (see Step 14).

> Avoid putting secrets in skill `env` unless you fully understand where those env vars are exposed and logged. Treat skill env injection as “host-process visible.”

---

## Step 13 — Build your invoicing workflow the safe way (avoid UI scraping)

Scraping your own web UI is fragile and increases attack surface. A safer design is to make your invoicing app produce **structured events**.

### 13.1 Add server-side events in your invoicing app
When:
- invoice uploaded → emit `invoice_uploaded`
- “PAID” button clicked → emit `invoice_paid`

Save authoritative state in your database (`paid_at`, `paid_by`, etc.).

### 13.2 Expose a minimal internal API for the agent
Example endpoints (conceptual):
- `GET /api/invoices?status=unpaid&month=YYYY-MM`
- `GET /api/creators/{id}/billing-status`
- `POST /api/notifications/send-reminder`

✅ This lets the agent work with JSON, not HTML pages.

### 13.3 Put the “reminder schedule” on the server
The most secure option is: reminders run as a normal backend cron job (no agent).
If you still want OpenClaw involved:
- Keep it as a **notification formatter/sender** only.
- The *decision logic* (who is unpaid) stays server-side.

---

## Step 14 — Create agents with least privilege

Use separate agents (or separate OpenClaw projects) with **explicit tool boundaries**.

### Agent A: Invoice Monitor (low risk)
- Allowed: call your internal API
- Deny: shell execution, arbitrary browsing, file writes

### Agent B: Notification Sender (medium risk)
- Allowed: messaging tool only
- Deny: browsing, shell, filesystem

### Agent C: External Data / “OnlyFans” (highest risk)
- Always sandboxed (`all`)
- No long-lived secrets (use broker token)
- Restrict network access to an allowlist (broker + required domains only, if supported)
- Separate workspace directory, minimal file permissions

> The win here is: even if Agent C is compromised, it cannot touch your invoicing database or messaging stack directly.

---

## Step 15 — Logging, transcripts, and redaction (quiet leaks are real)

Agents often leak secrets via:
- tool output
- stack traces
- “helpful” logs
- stored transcripts

**Do this:**
1. Enable redaction for tool outputs (and add custom patterns for anything that looks like a token).
2. Keep transcripts only as long as necessary.
3. Never copy/paste secrets into the chat “temporarily.”

After changing logging settings, run:

```bash
openclaw security audit --deep
```

---

## Step 16 — Skills safety rules (treat them as untrusted code)

Skills are powerful—and dangerous—because they run in your agent’s context.

**Hard rules:**
1. Start with **zero** third‑party skills until the base system is stable.
2. Before installing any skill:
   - Read `SKILL.md` and the full repo.
   - Reject anything that asks you to run:
     - `curl ... | bash`
     - `sudo ...`
     - `xattr -dr com.apple.quarantine ...`
     - base64/obfuscated commands
3. Run untrusted skills only in the **sandboxed External Data agent** with:
   - no long‑lived secrets
   - minimal filesystem access
4. Re-run security audit after adding skills.

---

## Step 17 — Ongoing operations (what keeps you safe over time)

### Weekly
- Update tooling:
  ```bash
  brew update
  brew upgrade
  ```
- Run:
  ```bash
  openclaw security audit --deep
  ```

### Before adding a new skill or new integration
- Snapshot the VM (or backup `~/OpenClaw` and `~/.openclaw`)
- Add the skill
- Re-run `openclaw security audit --deep`
- Test with **dummy/test keys** first

### If anything feels suspicious
- Disconnect network
- Revoke/rotate tokens immediately (broker tokens first)
- Wipe the VM or remove the `openclaw` user account and re-create it clean
- Restore from a known-good snapshot

---

# Appendix A — “Stop signs” (if you see these, stop)

- Any instructions to disable Gatekeeper or remove quarantine flags
- A skill that wants you to run `sudo` or install random “prerequisites”
- Any agent suggestion to paste API keys “just once”
- Any prompt that asks the agent to:
  - export environment variables
  - upload files/transcripts
  - read your home directory
  - visit random links to “fix install issues”

---

# Appendix B — Minimum viable secure checklist (fast review)

- [ ] Run OpenClaw in a VM or dedicated macOS user
- [ ] FileVault + Firewall enabled
- [ ] OpenClaw installed via Homebrew (or equally verifiable source)
- [ ] `spctl` and `codesign` verification passed
- [ ] `openclaw security audit --deep` clean (or understood + fixed)
- [ ] Gateway is localhost-only (not LAN/internet reachable)
- [ ] Sandboxing enabled and verified (`openclaw sandbox explain`)
- [ ] Agents split by risk; no “one agent does everything”
- [ ] Secrets handled via broker + short-lived tokens
- [ ] Redaction on; transcripts retained minimally
- [ ] No third-party skills without code review + sandboxing

---

If you want, paste (1) your current OpenClaw config file path + (2) the list of tools/skills you plan to enable, and I’ll rewrite your configuration into a least‑privilege, multi‑agent layout (with a broker-first secret strategy).
