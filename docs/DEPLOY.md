# Deploying FAULTLINE

Two public pieces, one local fallback:

| Piece | Where | Built from | Who deploys |
|---|---|---|---|
| Web app (static export of `apps/web`) | GitHub Pages at `FAULTLINE_PUBLIC_ORIGIN` (now `https://faultline.khayrul.com`) | `main`, automatically, by `.github/workflows/pages.yml` | a lead, by merging to `main` |
| API (`services/api`) | the lead's Debian/Ubuntu server at `FAULTLINE_API_HOST` (now `api.faultline.khayrul.com`), Docker Compose + Caddy | `main`, by `scripts/deploy-api.sh` | a lead, by hand |
| Local demo | the presenter's laptop, `make demo` | the local checkout | anyone |

Agents never deploy (AGENTS.md §2). Nothing in this repo contains a server IP, SSH user, SSH target, key or token:
those live only in the lead's `~/.ssh/config`, Cloudflare, GitHub settings, and `deploy/.env` on the server.

## Modes

| | `public` (server) | `local` (`make api`, `make demo`) |
|---|---|---|
| Set by | `FAULTLINE_MODE=public`, baked into `deploy/api.Dockerfile` and set in compose | default when `FAULTLINE_MODE` is unset |
| `/api/replay/run` (live model inference) | **refused (403 `ADMIN_TOKEN_REQUIRED`)** unless `Authorization: Bearer <FAULTLINE_ADMIN_TOKEN>` | open |
| What the audience sees | `RECORDED RUN` predictions + live deterministic `/api/simulate` and `/api/optimize` | everything live, against the laptop's Ollama |
| CORS allowlist | `FAULTLINE_CORS_ORIGINS`, else `FAULTLINE_PUBLIC_ORIGIN`; https origins only | the same, plus `http://localhost:3000` and `http://127.0.0.1:3000` |
| Rate limit | 120 requests/min per client IPv4 address, or per IPv6 /64 (`FAULTLINE_RATE_LIMIT_PER_MIN`) | off |
| Body limit | 64 KiB = 65,536 bytes (`FAULTLINE_MAX_BODY_BYTES`, and Caddy `request_body max_size 64KiB`) | 64 KiB |
| `/docs`, `/redoc`, `/openapi.json` | **off** (404) | on (generate web types locally) |

Every API response carries `X-Faultline-Mode: public|local` (also readable cross-origin), so
`curl -sI https://<api-host>/api/health | grep -i x-faultline-mode` tells you what is running.
The server is a CPU-only Xeon E5-2680 v4: an 8B model there takes minutes per forecast, which is why public mode
serves recorded runs and keeps inference behind the admin token.

## One-time setup

### 1. GitHub (repo settings, lead only)

1. **Settings > Pages > Build and deployment > Source: GitHub Actions.**
2. **Settings > Secrets and variables > Actions > Variables** (variables, not secrets; they are public names):
   - `FAULTLINE_PUBLIC_ORIGIN` = `https://faultline.khayrul.com`
   - `FAULTLINE_API_HOST` = `api.faultline.khayrul.com`

   The Pages workflow fails with a clear error if either is missing or malformed. It writes `CNAME` and `.nojekyll`
   into the build and sets `NEXT_PUBLIC_API_BASE=https://<FAULTLINE_API_HOST>`.
3. **Settings > Environments > github-pages > Deployment branches and tags:** only `main` (GitHub creates this
   rule when Pages uses Actions; check it is there).
4. After DNS (step 2 below) exists: **Settings > Pages > Custom domain:** `faultline.khayrul.com`, save, wait for the
   DNS check, then tick **Enforce HTTPS**. With Actions-based Pages, GitHub uses this setting; the `CNAME` file in
   the artifact is kept for parity but is not what GitHub reads.
5. Recommended: verify `khayrul.com` for your account (**Profile settings > Pages > Add a domain**, a TXT record in
   Cloudflare) so no other GitHub account can claim a subdomain of it.

### 2. Cloudflare DNS (lead only)

In the `khayrul.com` zone, **DNS > Records**:

| Type | Name | Content | Proxy status |
|---|---|---|---|
| `CNAME` | `faultline` | `lavishsphere.github.io` | **DNS only** (grey cloud) |
| `A` | `api.faultline` | the server's public IPv4 address | **DNS only** (grey cloud) |

**A record only; do not add an `AAAA` record for `api.faultline`.** With Docker's default port publishing
(`docker-proxy`), IPv6 clients reach Caddy with a single IPv4 source address, so every IPv6 visitor would share
one rate-limit bucket (one visitor could lock out all others). With Docker IPv6 enabled instead, a single client can
rotate through the addresses of its /64; the API keys IPv6 clients by /64 to blunt that, but this path has not been
tested on the server. IPv4-only keeps the per-IP limit meaning what it says.

Both must be DNS only: GitHub Pages and Caddy each issue their own Let's Encrypt certificate and need to see the
real hostname, and the API's per-IP rate limit needs real client addresses (behind the orange cloud every request
would come from a Cloudflare IP). Check with `dig +short faultline.khayrul.com` (should show `lavishsphere.github.io`)
and `dig +short api.faultline.khayrul.com` (the server).

### 3. Server (Debian 12 / Ubuntu 22.04+, lead only)

```bash
# Docker Engine + compose plugin from Docker's apt repository:
#   https://docs.docker.com/engine/install/debian/   or   https://docs.docker.com/engine/install/ubuntu/
sudo usermod -aG docker "$USER"   # log out and back in. (docker group = root-equivalent; your account only.)

# Firewall: SSH plus 80/443 only.
sudo apt-get install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH            # keep this, or you lock yourself out
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp            # HTTP/3
sudo ufw enable

# The repo (read-only clone; for a private repo use a read-only deploy key).
git clone https://github.com/LavishSphere/faultline.git ~/faultline
cd ~/faultline
cp deploy/.env.example deploy/.env
chmod 600 deploy/.env
"${EDITOR:-nano}" deploy/.env     # names as above; leave FAULTLINE_ADMIN_TOKEN empty unless you need live inference
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml ps
```

#### First-deploy checklist (this layout has not been run before; verify each line)

Caddy sits on an internal network (`edge`, to reach the api) and a normal one (`public`, for published ports and
Let's Encrypt). That combination has not been exercised on this server yet, so check it explicitly:

1. `docker compose -f deploy/docker-compose.yml ps`: `api` is `healthy`, `caddy` is `running`.
2. Ports are published on the host: `sudo ss -tlnp | grep -E ':(80|443) '` shows docker-proxy (or the Docker
   iptables rules) on 80 and 443; nothing listens on 8000 or 11434.
3. ACME worked: `docker compose -f deploy/docker-compose.yml logs caddy | grep -iE 'certificate obtained|error'`
   shows "certificate obtained successfully" for the API host and no errors.
4. From your laptop: `curl -sI https://api.faultline.khayrul.com/api/health` returns `HTTP/2 200` and
   `x-faultline-mode: public`; `curl -s -o /dev/null -w '%{http_code}\n' -X POST https://api.faultline.khayrul.com/api/replay/run`
   prints `403`; `curl -s -o /dev/null -w '%{http_code}\n' https://api.faultline.khayrul.com/docs` prints `404`.
5. The api has no internet: `docker compose -f deploy/docker-compose.yml exec api python -c "import urllib.request; urllib.request.urlopen('https://example.com', timeout=5)"` must fail.

If step 2 or 3 fails because Caddy has no outbound route or its ports are not reachable, Docker may have picked
the internal network as Caddy's default gateway. Docker Engine 28+ / Compose 2.33+ let you pin it: in
`deploy/docker-compose.yml`, change caddy's `networks: [public, edge]` to

```yaml
    networks:
      public:
        gw_priority: 1
      edge: {}
```

then `docker compose -f deploy/docker-compose.yml up -d` and repeat the checklist.

Docker writes its own iptables rules, so a port published by a container bypasses ufw. That is why only Caddy
publishes ports (80/443) and the API and Ollama publish none; do not add `ports:` to them.

For live inference on the server, set a token: `openssl rand -hex 32`, paste the output after
`FAULTLINE_ADMIN_TOKEN=` in `deploy/.env` (at least 32 characters; a shorter value stops the API at startup), then
`docker compose -f deploy/docker-compose.yml up -d`. Note that `docker compose config` prints it.

## Deploying

Web: merge to `main`. The `pages` workflow builds and deploys; watch it under **Actions > pages**.

API, from the lead's laptop after the merge:

```bash
make deploy-api SSH=<ssh-host-alias>                 # or: FAULTLINE_DEPLOY_SSH=<alias> scripts/deploy-api.sh
```

The script SSHes in, refuses if the server checkout is dirty or not on `main`, runs `git pull --ff-only origin main`
and `docker compose -f deploy/docker-compose.yml up -d --build`, waits for the api container to be healthy, then
checks `https://<FAULTLINE_API_HOST>/api/health` from your laptop and requires `X-Faultline-Mode: public`. It prints
the previous commit for rollback. Optional: `FAULTLINE_DEPLOY_DIR` (clone path on the server, default `faultline`
in the remote home) and `FAULTLINE_API_HOST` (otherwise read from the server's `deploy/.env`).

## What protects the API

- **Network:** Caddy is the only container with published ports. `edge` (Caddy and api) and `models` (api and ollama)
  are `internal: true` networks, so the api and Ollama containers have no route to the internet at runtime.
  Consequence: `ANTHROPIC_API_KEY` / `TAVILY_API_KEY` features cannot work on the server (they stay disabled).
- **Containers:** api runs as uid 10001 with a read-only root filesystem (writable: the `api-var` volume at
  `/app/var` and a small `/tmp` tmpfs), all capabilities dropped, `no-new-privileges`, 2 GB memory and 256 pids.
  Caddy: all capabilities dropped except `NET_BIND_SERVICE`, read-only. Ollama: the image has no non-root user,
  so it runs as uid 0 but with all capabilities dropped, `no-new-privileges`, 32 GB memory and 512 pids.
- **CORS:** allowlist only, methods GET/POST, header `Content-Type`, no credentials. `Authorization` is not an
  allowed header, so a browser page cannot send the admin token cross-origin; use it from a terminal.
- **Client address:** Caddy overwrites `X-Forwarded-For` with the TCP peer (`header_up X-Forwarded-For
  {remote_host}`), so it carries exactly one, unspoofable entry; uvicorn (`--proxy-headers`) uses it as the client IP.
- **Beyond CORS** (CORS only binds browsers): per-IP token-bucket rate limit (429 with `Retry-After`), body limit
  (413), and the public-mode admin gate on `/api/replay/run` (and any path under it), all at the ASGI layer and
  covered by `services/api/tests/test_deploy_config.py`. The limiter is in-process; the image runs one uvicorn
  worker, so the configured number is the real limit (with N workers it would be N times higher).
- **No API explorer in public:** `/docs`, `/redoc` and `/openapi.json` return 404 in public mode.

Admin call (lead's terminal):

```bash
curl -sS -X POST "https://api.faultline.khayrul.com/api/replay/run" \
  -H "Authorization: Bearer $FAULTLINE_ADMIN_TOKEN" -H "Content-Type: application/json" -d @request.json
```

## Optional: Ollama on the server

`COMPOSE_PROFILES=ollama` in `deploy/.env` (or `--profile ollama`) starts `ollama/ollama` on the internal `models`
network: CPU only, 32 GB memory limit, never published. Because that network has no internet access, pull models
out of band into the same volume:

```bash
docker run -d --rm --name ollama-pull -v faultline_ollama-models:/root/.ollama ollama/ollama:0.40.16
docker exec ollama-pull ollama pull llama3.1:8b
docker stop ollama-pull
docker compose -f deploy/docker-compose.yml --profile ollama up -d
```

`/api/health` then reports `ollama: true` and whether `FAULTLINE_OLLAMA_MODEL` is installed. Without the profile it
honestly reports Ollama unreachable; replay inference returns `MODEL_UNAVAILABLE`, never a canned answer.

## Renaming the subdomain

The names live in exactly these places; change all of them together:

1. Cloudflare: rename the `CNAME` and `A` records (same targets).
2. GitHub repo variables `FAULTLINE_PUBLIC_ORIGIN` and `FAULTLINE_API_HOST`.
3. GitHub **Settings > Pages > Custom domain** (the new site host), then Enforce HTTPS again once the cert is issued.
4. Server `deploy/.env`: `FAULTLINE_PUBLIC_ORIGIN` and `FAULTLINE_API_HOST`; then `make deploy-api` (Caddy gets a
   certificate for the new host on first request).
5. Re-run the web deploy so the new API base is baked into the static build: merge any change to `main`, or
   **Actions > pages > latest run > Re-run all jobs**.

The defaults in `services/api/config.py` (`DEFAULT_PUBLIC_ORIGIN`) and `deploy/.env.example` are only fallbacks
and documentation; update them in a normal PR when convenient.

## Rollback

- **API:** on the server, `cd ~/faultline && git log --oneline -5`, then
  `git checkout <previous-sha> && docker compose -f deploy/docker-compose.yml up -d --build`
  (`scripts/deploy-api.sh` printed the previous sha). Return to normal with `git switch main` before the next
  `make deploy-api` (the script refuses a detached checkout). Volumes (`api-var`, certificates, models) are kept.
- **Web:** revert the bad PR on `main` (a new PR; the merge redeploys), or for an immediate fix open
  **Actions > pages**, pick the last good run on `main`, **Re-run all jobs**: it redeploys that commit's build.
- **Take the API offline:** `docker compose -f deploy/docker-compose.yml down` (the web app then shows
  "API unavailable" / NOT AVAILABLE, not fake data).

## Local demo mode (pitch fallback)

```bash
make setup          # once, with internet: API venv + web node_modules
ollama serve &      # local model server; `ollama pull llama3.1:8b` once, with internet
make demo           # API on http://127.0.0.1:8000 (FAULTLINE_MODE=local), web on http://127.0.0.1:3000
```

Both processes bind to 127.0.0.1 only. Live replay runs against the laptop's Ollama with no token and no rate
limit, and works with Wi-Fi off once the steps above have run (fonts are self-hosted, replay makes no outbound
calls). If Ollama is not running, `make demo` warns and replay shows `MODEL_UNAVAILABLE`.

## Troubleshooting

- Pages workflow fails at "Read and validate repo variables": set the two repo variables (section 1).
- Browser shows "API unavailable" on the hosted site: check `curl -sI https://<api-host>/api/health`; the site
  origin must be in the CORS allowlist (`FAULTLINE_PUBLIC_ORIGIN` / `FAULTLINE_CORS_ORIGINS` in `deploy/.env`).
- Caddy cannot get a certificate: DNS must be DNS only and point at the server; ports 80 and 443 must be open.
- The API refuses to start with a `ConfigError`: a value in `deploy/.env` is malformed (e.g. an `http://` CORS
  origin in public mode, a wildcard, a non-numeric port, a non-integer limit, or an admin token under 32 chars). `docker compose -f deploy/docker-compose.yml logs api`.
