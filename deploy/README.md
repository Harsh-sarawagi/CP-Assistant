# One-VM deployment

The owner reports the current HTTPS deployment is working at
https://130-210-110-62.sslip.io on a 1 OCPU ARM64 VM. The repository limits are
web=1.0, PostgreSQL=1.0 and Nginx=0.5 CPUs. For an existing deployment, use the
update procedure rather than fresh database initialization; never regenerate its
environment file or replace its database volume. Live state was not inspected by SSH.


Three containers: Django/Gunicorn, PostgreSQL 17 and Nginx. Certbot runs on the Ubuntu
host using its existing systemd timer. No paid service, Redis, workers or CI/CD is needed.
Only ports 80 and 443 are published. Static files are collected into the image and
served by WhiteNoise. Notes, users, sessions and extension grants live in PostgreSQL.

## 1. Oracle and domain

Create an **Always Free-eligible Ubuntu 24.04 ARM64** A1 VM in your home region. The
current Always Free documentation lists 2 OCPUs/12 GB RAM and 200 GB combined boot/block
storage across the account; confirm your own console allocation. A 50-60 GB boot disk
is enough to start. Capacity and idle-instance reclamation can affect availability.

Point a domain/subdomain's A record to the VM's public IPv4 address. An existing or
free DNS hostname avoids domain purchase. Add AAAA only if IPv6 is actually configured.
In Oracle's network security rules, allow TCP 80/443 publicly and SSH 22 only from your
IP. Do not allow 5432 or 8000. Do not rely on UFW alone for Docker-published ports.

## 2. Install Docker and Certbot on Ubuntu

Run these on the VM, not in Windows PowerShell. These commands assume a clean Ubuntu
VM without conflicting older Docker packages.

```bash
sudo apt update
sudo apt install -y ca-certificates curl python3 certbot
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
sudo mkdir -p /opt/cp-assistant
sudo chown "$USER":"$USER" /opt/cp-assistant
```

Copy the **current reviewed source** into `/opt/cp-assistant`, including `compose.yaml`,
`gunicorn.conf.py`, `.env.production.example`, `deploy/`, `scripts/`, `config/`, `core/`
and all three migrations. These deployment changes are initially uncommitted: cloning
the earlier remote revision alone will not include them. Alternatively commit/push the
reviewed files yourself and clone that revision. Do not upload the Windows virtual
environment, local `.env`, SQLite files, database backups, or generated static files.

## 3. Configure production secrets

```bash
cd /opt/cp-assistant
python3 scripts/prepare_production.py --domain cp.your-domain.com --extension-id YOUR_32_LETTER_EXTENSION_ID
chmod 600 .env.production
nano .env.production
```

Replace both arguments with real values. The script creates fresh Django, database and
database-administrator secrets without displaying them. It refuses to overwrite a file.
A private `.env.production` was also generated locally during implementation; if you
transfer that file privately instead, edit its placeholder domain and extension ID and
skip generation. Never copy the exposed old Django secret or reuse the local `.env`.
The locally prepared file already contains the existing valid extension ID and AI
configuration where available; the generator on a fresh VM leaves the AI key blank.

`DOMAIN` is a hostname without scheme, path or port. Blank `ALLOWED_HOSTS` and
`CSRF_TRUSTED_ORIGINS` default to that hostname and its HTTPS origin. Add your Groq key
to `AI_API_KEY` only if you want AI features; leaving it empty disables live inference.
Never print `docker compose config` or share this environment file; use `config --quiet`.

Define this shortcut again in each new SSH session:

```bash
cd /opt/cp-assistant
dc() { sudo docker compose --env-file .env.production "$@"; }
dc config --quiet
dc build web
```

The image builds natively on ARM64. No production secret or database is needed at build
time. The application runs as an unprivileged user and PostgreSQL creates a separate
non-superuser application role. Passwords initialize a **new empty volume only**;
editing them later does not change database passwords. Do not regenerate the env file
after initialization without planning credential changes.

## 4. Get free HTTPS before exposing the app

This bootstrap starts Nginx only, without creating a production database or exposing
login pages. DNS must already point to this VM and TCP port 80 must be reachable.

```bash
mkdir -p deploy/acme
sudo env NGINX_TEMPLATE=./deploy/nginx/http.conf.template docker compose --env-file .env.production up -d --no-deps nginx
DOMAIN=$(sed -n 's/^DOMAIN=//p' .env.production)
sudo certbot certonly --webroot -w /opt/cp-assistant/deploy/acme --cert-name "$DOMAIN" -d "$DOMAIN" --email YOUR_EMAIL --agree-tos --no-eff-email
```

Certificates stay on the host in `/etc/letsencrypt`, mounted read-only into Nginx.
Bootstrap returns 503 for all paths except the ACME challenge. Do not expose Gunicorn
directly to bypass HTTPS. The normal Compose configuration switches to TLS in step 5.

## 5. Start with an approved fresh database

**Run this section only after the owner explicitly approves a fresh production database.**
It initializes a new Docker volume; it does not connect to or transfer the existing
Windows PostgreSQL database. No data transfer is automated. For an existing database
restore, stop here and agree on a separate backup/restore plan first.

```bash
dc up -d --wait db
dc run --rm --no-deps web python manage.py migrate --plan
dc run --rm --no-deps web python manage.py migrate --noinput
dc run --rm --no-deps web python manage.py check --deploy
dc up -d --wait
dc exec web python manage.py createsuperuser
dc ps
curl -I "https://$DOMAIN/register/"
curl "https://$DOMAIN/api/extension/auth/status/"
```

Open `https://YOUR_DOMAIN/register/`, create your normal account, then log in. Verify
the dashboard and save a notebook entry. The database volume is named
`cp-assistant_postgres_data`. Keep the same project name. Do not use `down --volumes`,
`down -v`, volume deletion, or a global Docker prune against production data.

The internal `/health/` checks only PostgreSQL with `SELECT 1`; it makes no AI/Codeforces
calls. Nginx blocks it publicly. Secure cookies, exact hosts/origins, HTTPS proxy
recognition and a short HSTS policy are enabled only in `config.production`. Local
`manage.py runserver` keeps using `config.settings`.

`check --deploy` reports W005/W021 because HSTS subdomain coverage and browser preload
are deliberately disabled. The one-hour HTTPS policy covers the application hostname;
do not enable a wider/long-lived policy just to suppress warnings before reviewing DNS.

## 6. Automatic certificate renewal

```bash
sudo install -d -m 0755 /etc/letsencrypt/renewal-hooks/deploy
sudo install -m 0755 deploy/renew-nginx.sh /etc/letsencrypt/renewal-hooks/deploy/cp-assistant
sudo systemctl enable --now certbot.timer
sudo certbot renew --dry-run
```

Certbot's timer renews eligible certificates; the deploy hook validates and reloads
Nginx after renewal. The hook assumes `/opt/cp-assistant`; adjust that path if you used
another location. The HTTP challenge path remains available after HTTPS is enabled.

## 7. Connect the Chrome extension

1. Load/reload the current `extension/` in Chrome Developer Mode.
2. Check its ID matches `EXTENSION_ALLOWED_IDS` on the VM. Unpacked IDs can differ
   between machines; allowlist exact IDs, never a wildcard.
3. Open Options, set `https://YOUR_DOMAIN`, save and grant the requested host permission.
4. Open a Codeforces profile, click **Connect Account**, log in on the production
   website and approve the connection. Changing backend deliberately clears old access.
5. Save your Codeforces handle in website profile settings to show personal tabs on
   that profile. Public profiles show Overview only.

Website login uses secure same-site cookies. The extension worker uses PKCE and Bearer
credentials, not cross-site session cookies. Do not set SameSite=None or exempt website
CSRF to make it work. No API keys belong in the extension. Overview and health checks
never call Groq; AI plans/reviews require an explicit action. Plan quotas remain active.

## 8. Restart and update

Restart without changing data:

```bash
dc restart web nginx
```

Before updating source or database schema, save a private backup and copy it off the VM:

```bash
umask 077
mkdir -p backups
dc exec -T db sh -c 'pg_dump -U cp_admin -d "$DB_NAME" -Fc' > "backups/pre-update-$(date +%Y%m%d-%H%M%S).dump"
dc stop nginx web
# Upload the reviewed new source, or git pull an explicitly reviewed release.
dc build web
dc run --rm --no-deps web python manage.py migrate --plan
# Run only after reviewing/approving the migration plan:
dc run --rm --no-deps web python manage.py migrate --noinput
dc run --rm --no-deps web python manage.py check --deploy
dc up -d --wait
```

Never run `makemigrations` on the VM. A volume survives container recreation, not disk
loss; retain off-VM backups and test restoration separately. Keep PostgreSQL on major
version 17 until you plan an upgrade. Logs rotate automatically; avoid sharing logs
containing user data. Groq quotas/billing depend on your account; this setup does not
upgrade plans or make paid requests during deployment.

## Optional isolated verification

```bash
python3 scripts/verify_deployment.py
```

This builds the image, creates a randomly named test Compose project/database, runs
migrations/checks, trusts a temporary localhost certificate, tests website sessions,
PKCE/CORS, static assets and mocked AI review, then recreates the containers to test
persistence. It removes **only its own test volume**. It never loads the real env file.
Ports 18080/18443 must be free. On an engine supporting ARM emulation, add
`--platform linux/arm64`; native Oracle builds already use ARM64.

Sources: [Docker Ubuntu installation](https://docs.docker.com/engine/install/ubuntu/),
[Oracle Always Free limits](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm),
[Certbot webroot/renewal](https://eff-certbot.readthedocs.io/en/stable/using.html#webroot).
