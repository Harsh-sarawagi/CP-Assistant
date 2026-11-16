# Temporary public HTTP test — 130.210.110.62

This is an anonymous, database-free smoke test, not the full website. It keeps
`config/production.py`, `compose.yaml` and the HTTPS Nginx configuration unchanged.
Do not enter credentials or connect the extension to this HTTP address.

## Reviewed surface

| Path | Methods | Purpose |
| --- | --- | --- |
| `/` | GET, HEAD | New status-only landing page, without the existing login form |
| `/api/profiles/{handle}/analytics/` | GET | Existing public Codeforces statistics |
| `/api/profiles/{handle}/weaknesses/` | GET | Existing public deterministic weakness statistics |
| `/api/profiles/{handle}/practice/` | GET | Existing public deterministic recommendations |
| `/health/` | GET, HEAD | Internal database-free liveness; Nginx blocks public access |

These APIs read public Codeforces data and write only disposable in-memory caches and
rate counters. They do not query accounts/notes or call Groq. Public GET requests can
call Codeforces on a cache miss. Local verification mocks those requests.

Every other route and method is denied **in Django before other middleware**. The
original root login POST, GET logout, registration, profile changes, dashboard, AI
review/plans, private notes, all extension auth/connection endpoints, admin login/logout/
password actions, password-reset aliases and unknown future routes are unavailable.
There are no sessions, authentication or messages middleware in this mode; no cookies
are issued. Requests carrying Cookie/Authorization headers, query strings, request
bodies or method-override headers are also denied. Use curl or a clean private window.

The allowlist checks resolved view identity, route name and method. It does not depend
on a short list of prohibited prefixes. Static/admin assets are not exposed. Secure
cookie flags remain enabled, although no cookies are used. HTTPS redirect and HSTS are
disabled only in `config.http_test`.

## Database policy

**No database initialization, migration or data transfer is needed or permitted here.**
Django uses the dummy database backend. The override removes database dependencies,
volume definitions, TLS mounts and the HTTPS port. PostgreSQL is in a disabled profile
with a blocking entrypoint. Never enable that profile or run `migrate` in HTTP mode.
Existing local/production PostgreSQL databases and volumes are not used.

A fresh database for the complete HTTPS deployment still requires separate explicit
owner approval. Do not try to re-enable account features in this HTTP configuration.

## Exact VM commands (documented only; not executed remotely)

First copy the current reviewed files to `/opt/cp-assistant`, including the new override,
settings, guard, URL configuration, HTTP Nginx template and scripts. These changes have
not been committed/pushed automatically; an older clone will not contain them.

Install Docker using section 2 of [the existing deployment guide](README.md). Use
Docker Compose **2.24.4 or newer** for `!reset`/`!override`. Do not follow that guide's
production database or certificate-startup steps for this temporary test.

On the Oracle VM, once deployment is approved:

```bash
cd /opt/cp-assistant
python3 scripts/prepare_production.py --domain 130.210.110.62 --output .env.http-test
chmod 600 .env.http-test
htc() { sudo docker compose --env-file .env.http-test -f compose.yaml -f compose.http-test.yaml "$@"; }
htc config --quiet
htc build web
htc up -d --wait web nginx
htc ps
```

The generated file is separate from `.env.production`, ignored by Git/Docker and never
printed. Its database variables satisfy base-file interpolation only; PostgreSQL is
not started, and the web service never receives production database credentials.
The override clears the AI key and extension allowlist regardless of environment input.

Allow inbound TCP 80 in the VM's Oracle security rules and host firewall after review;
retain restricted SSH access. Do not open 8000, 5432 or 443 for this test. If port 80 is
already occupied, do not stop an existing HTTPS stack without approval. Select another
`HTTP_TEST_PORT` in `.env.http-test` and review its ingress rule separately instead.

From your own computer:

```bash
curl -i http://130.210.110.62/
curl -i http://130.210.110.62/register/
curl -i -X POST http://130.210.110.62/
curl -i http://130.210.110.62/logout/
curl -i http://130.210.110.62/api/extension/auth/status/
# Optional free upstream request, not an AI call:
curl -i http://130.210.110.62/api/profiles/tourist/analytics/
```

Expect 200 for the status page, 403 without redirects/cookies for sensitive routes,
and public JSON (or an upstream error) for the analytics API. Internal `/health/`
returns 404 through Nginx. There must be no HSTS or authentication cookies.

Stop/remove only the temporary stack:

```bash
htc down
```

Do not use `down -v`, delete volumes, or run the base Compose file by itself as an HTTP
workaround. The separate project name prevents reuse of the production project's data.
For the full application, stop this temporary stack and return to the unchanged HTTPS
deployment only after the usual hostname, certificate and database approvals.

## Local verification (no database)

```powershell
.\.venv\Scripts\python.exe -B scripts/verify_http_test.py
# With Docker available on PATH:
.\.venv\Scripts\python.exe -B scripts/verify_http_test.py --docker docker
```

The tests enumerate the existing core routes, cover admin/password aliases, forged
HTTPS headers, cookies/Bearer credentials, URL variants, all write methods and future
unknown paths. Public API results are mocked. The optional Docker run creates only
web/Nginx on loopback port 18081, asserts that no database container or volume exists,
and removes its own temporary containers/networks afterward. It never initializes a DB.

Compose merge semantics: [official Docker documentation](https://docs.docker.com/reference/compose-file/merge/).

## Verification results — 17 November 2026

- Five HTTP security test groups passed, including enumeration of existing core routes
  across seven HTTP methods, admin/password aliases and default-deny checks.
- All 31 existing offline regression tests passed; standard Django checks passed.
- The HTTP image built and the local web/Nginx stack started successfully. Real HTTP
  requests returned 200 for the new landing page and 403 for sensitive routes without
  authentication cookies, redirects or HSTS. Internal liveness stayed private.
- The resolved Compose configuration and running project had no PostgreSQL service
  started, no published Gunicorn port and no database volumes. No migrations were run.
- Public analytics were tested using mocks, with all outbound HTTP forbidden during
  application tests. No live Codeforces or paid Groq verification was performed.
- SHA-256 comparisons confirmed `config/production.py`, `compose.yaml`, and the existing
  HTTPS Nginx template were byte-for-byte unchanged during this task.
- No Oracle deployment or database initialization was performed. Temporary local test
  containers/networks were removed. No commits/pushes were made.
