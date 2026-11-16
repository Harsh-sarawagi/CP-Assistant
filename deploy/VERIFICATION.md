# Local deployment verification

Historical initial-deployment results. For the latest repository changes, test counts,
release commands and deployment requirements, see [the final audit](../FINAL_AUDIT.md).

Completed 17 November 2026. No Oracle resources were provisioned, no production database
was initialized, and no commits or pushes were made for this deployment implementation.

## Configuration delivered

- `Dockerfile`: Python 3.11 Debian image, compressed/hashed static assets, non-root
  application user, production settings by default, and bounded numerical-library threads.
- `compose.yaml`: three services only; persistent PostgreSQL 17 volume; database and
  application health checks; restart policies, memory/CPU limits and rotating logs.
  Only Nginx publishes ports. PostgreSQL uses a dedicated non-superuser application role.
- `gunicorn.conf.py`: one process, four threads, bounded request recycling and timeouts.
  Access logs omit query strings, credentials and request bodies.
- `config/production.py`: fail-closed configuration validation, DEBUG=False, exact hosts,
  HTTPS CSRF origins, secure cookies and proxy scheme handling. Local settings remain separate.
- `config/health.py`: read-only PostgreSQL readiness; no Codeforces or AI requests.
  Nginx blocks the readiness route publicly.
- `deploy/nginx/`: HTTPS reverse proxy, HTTP redirect, and certificate bootstrap configuration.
  Bootstrap exposes only ACME challenges; it does not expose login over plain HTTP.
- `deploy/postgres/init-app.sh`: initializes only a newly created Docker database volume.
- `deploy/renew-nginx.sh`: Certbot renewal deploy hook for `/opt/cp-assistant`.
- `.dockerignore`/`.gitignore`: exclude environments, credentials, databases, backups and
  generated files. Shareable environment templates remain available.
- `scripts/prepare_production.py`: creates fresh secrets privately and refuses overwrites.
- `scripts/verify_deployment.py`: isolated Docker integration verification and cleanup.
- `requirements.txt`: Django patched from 5.2.14 to 5.2.19 within the existing LTS series.
- `core/services/extension_auth.py`: production rate limits use the client IP overwritten
  by the private Nginx proxy. Local requests continue using REMOTE_ADDR.

## Results

| Check | Result |
| --- | --- |
| Linux AMD64 Docker build/startup | Passed |
| Linux ARM64 Docker build/startup under local emulation | Passed; native Oracle hardware not tested |
| Full Python application suite in isolated PostgreSQL | 65 tests passed on both architectures |
| JavaScript extension/review suite | 30 tests passed |
| Fresh test-database migrations | All existing migrations applied successfully |
| Standard Django checks/model drift | Passed; no new migration needed |
| Production Django checks | Passed with two intentional HSTS policy warnings below |
| Secure website registration, login and sessions | Passed through the HTTPS proxy |
| HTTP redirect / hashed static CSS | Passed |
| Existing editor limit after UTF-8 form encoding | Passed without a provider call |
| Extension PKCE/consent/code exchange | Passed through HTTPS with a test extension ID |
| Bearer authentication/CORS preflight | Passed |
| Mocked AI code-review integration | Passed; no paid inference |
| Container recreation with retained PostgreSQL volume | Accounts, notes, sessions and grants preserved |
| Refresh renewal after recreation | Passed |
| No public PostgreSQL/Gunicorn host ports | Checked in resolved Compose configuration |
| Local database preservation | Before/after PostgreSQL fingerprints matched; both legacy SQLite hashes unchanged |
| Test cleanup | No temporary verification containers or volumes remain |

The test certificate is self-signed and trusted only by the verification script.
No public certificate was issued, no system trust store was changed, and no real
Chrome authorization popup was exercised. Paid Groq calls were replaced with mocks;
the test backend had no live AI key.

`security.W005` and `security.W021` remain deliberately visible: HSTS covers the
application hostname for one hour, without subdomain coverage or browser preload.
Do not enable a broader policy simply to silence these warnings.

## Private production environment

An ignored `.env.production` was generated locally with a fresh Django secret and new
database credentials, distinct from the existing local configuration. Existing public
extension ID and AI configuration were copied where available without displaying them.
The placeholder DOMAIN must be replaced before production startup. The file is excluded
from Git and the Docker image. The original `.env` was not edited.

## Manual work still required

Follow [the deployment guide](README.md) for exact commands:

1. Create the Always Free-eligible Ubuntu ARM64 VM and configure DNS/security rules.
2. Transfer the reviewed current source and configure the private production environment.
3. Bootstrap Nginx, issue the free certificate and configure its renewal hook/timer.
4. Obtain explicit owner approval for a fresh production database before initialization.
   No local database transfer or restoration is automated.
5. Start the application, set the extension's HTTPS backend URL and reconnect.
6. Verify the actual public hostname, certificate renewal and Chrome account flow manually.
