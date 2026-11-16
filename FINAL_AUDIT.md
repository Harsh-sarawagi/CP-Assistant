# CP Assistant: final repository audit

Date: 17 November 2026. Scope: Django views/models/services and migrations, website
templates/static assets, extension worker/content script/options/popup, tests, Docker/
Compose/Nginx/Certbot scripts, environment examples, ignore rules, docs and Git history.

## Readiness and limits

The owner reports the Oracle ARM64 HTTPS deployment, Certbot renewal, AI and extension
are working at https://130-210-110-62.sslip.io. No SSH connection, VM configuration change,
production database operation or paid AI request was made during this audit. Read-only
public URL checks were unavailable through the browsing tool; that is not evidence that
the site is down. The live VM's actual configuration, backups and renewal timer were
not independently inspected. Local tests exercise representative repository settings.

The repository fixes below are ready for review/release. Credential rotation is an
outstanding manual security action. The working tree also contains previously prepared
deployment/HTTP-test files that were already uncommitted when this audit began.

## Confirmed findings and minimal fixes

| Finding | Change | Deployment effect |
| --- | --- | --- |
| `compose.yaml` allowed 1.5 CPUs for web on the stated 1 OCPU VM | Web now 1.0; db 1.0 and nginx 0.5 retained; verifier checks all limits | Apply reviewed Compose configuration without replacing data |
| Common settings hardcoded PostgreSQL, inconsistent with the intended SQLite development setup | `DB_ENGINE=sqlite` supported; fresh setups default SQLite; legacy environments with DB_NAME retain PostgreSQL unless selected explicitly | Local choice only; no database transfer performed |
| A local SQLite selection must not leak into production | Production constructs its own PostgreSQL backend explicitly | Deploy production settings fix; database/role/volume unchanged |
| GET logout changed session state and allowed cross-site logout | CSRF-protected POST, matching navigation form and tests | Rebuild web/templates together; refresh old browser pages |
| Malformed third-party contest-feed JSON could break the login page | Handle feed format/type failures and render the page without contests | Rebuild web; no feature/data change |
| In-flight extension credentials could be bound to a newly chosen backend | Bind start/exchange/refresh/authenticated requests and stored credentials to their issuing backend; regression test added | Reload unpacked extension and refresh Codeforces tabs |
| Environment example lacked the database selection/optional PG fields and used an inconsistent model default | Local and production examples now document their actual settings without credentials | Documentation only; real environment files were not edited |
| Ignore rules missed some common credential/export formats | Expanded Git/Docker exclusions for env variants, keys, database files and dumps | No existing database or backup was deleted |

The legacy local `.env` has no DB_ENGINE selector. If SQLite is intended, select it
explicitly as documented and back up/apply local migrations deliberately. The audit
does not silently move existing PostgreSQL data into SQLite or alter the real `.env`.

## Security review

- **Urgent manual action:** the IDE context contained a Groq key. Revoke/replace that key
  in Groq and privately update each affected local/production environment. Recreate web
  to pick up a changed Compose environment. The key is not reproduced here or in source.
- Pattern scans found no recognized real provider keys/private keys in the shareable
  working tree, and no currently tracked files match the expanded ignore rules. This
  is a targeted scan, not a guarantee against every possible secret format.
- Available Git history contains an old hardcoded Django secret. The prepared local
  production secret differs from it. Never use the historical value in production;
  the live VM's secret was not inspected. History rewriting was not attempted.
- Production enforces DEBUG=False, explicit hosts/HTTPS CSRF origins, secure cookies and
  proxy scheme handling. Gunicorn has no public host port; Nginx overwrites forwarding
  headers. Trusting those headers relies on keeping Gunicorn private.
- Website writes retain CSRF. Extension private APIs require scoped Bearer proof,
  PKCE/state/single-use consent, expiration/revocation and rotating refresh credentials.
  Cookie-only authentication is not accepted on private extension APIs. PostgreSQL
  locks enforce note ownership/conflict checks and AI-plan quotas.
- Extension credentials stay in trusted-context storage and are bound to a backend.
  No provider key is shipped in the extension. Optional HTTPS permissions are granted
  only for the selected backend; localhost defaults and loopback test URLs are intentional.
- User source, notes and AI text are escaped; review URLs are constrained to Codeforces;
  scraping does not follow redirects. Source code is not executed by this application.
- Groq is called only by explicit review/plan actions. Health checks and deterministic
  profile loading do not trigger inference.
- HSTS subdomain/preload warnings W005/W021 remain intentional. No security warnings
  were hidden or cookie/CSRF requirements weakened to quiet checks.

## Verified in this audit

| Verification | Result |
| --- | --- |
| Isolated Docker build/Compose startup | Passed, Linux AMD64 locally; ARM64 was tested in the earlier deployment phase |
| Full application tests against fresh isolated PostgreSQL | 68 passed |
| SQLite test runner | 73 discovered: 68 passed, 5 HTTP-only tests skipped as intended |
| HTTP-only settings tests | 5 passed, without database access or external calls |
| Offline analytics/AI/configuration suite | 33 passed |
| JavaScript extension/review tests | 31 passed, including late-refresh/backend-switch protection |
| Real local HTTPS reverse proxy | Registration/login, secure cookies, POST logout, PKCE, CORS, private notes and static files passed |
| Container recreation | Test accounts, notes, sessions and grants retained; refresh renewal passed |
| Schema drift and standard Django checks | No new migration; no standard check issues |
| Production deployment checks | Passed with intentional W005/W021 policy warnings |
| Dependencies/syntax | Local pip check passed; Python/manifest parsed; Docker installed the pinned requirements |
| Existing data | No existing local/production DB was used for integration writes; test databases were separate |

The local virtual environment is older than the pinned Docker environment (Django
5.2.14 locally versus 5.2.19 in Docker). Update local dependencies using requirements.txt
when ready. The production-compatible tests run inside the pinned Docker image.
The pinned 5.2.19 is the current 5.2 LTS patch listed by the
[Django project](https://www.djangoproject.com/download/). This was not an exhaustive
dependency CVE audit; newer major versions were not introduced unnecessarily.

## Remaining risks and optional improvements

- Key rotation above is required; ignore rules cannot revoke an exposed key or erase history.
- Live certificate renewal, off-VM backups/restoration and native VM resource usage remain
  operator checks. Do not substitute a passing local smoke test for those checks.
- Code review lacks the AI plan's per-account hourly quota, and login has no dedicated
  brute-force throttle. Nginx provides general rate limiting. Consider tighter endpoint
  limits before wider public use; no new infrastructure was added in this audit.
- Public cache/rate limits are process-local; cold Codeforces requests and third-party
  availability can affect latency. Existing single-process Gunicorn configuration is retained.
- Legacy unused Google SDK dependencies/templates can be cleaned up separately after
  consumer review. They were not removed during a production-preserving audit.
- The temporary HTTP override must not be used to restore authentication over plaintext.

## GitHub status and exact release commands

Read-only comparison: local committed HEAD and GitHub origin/main both point to
`54340522a9dc31b7c185b8b7fccdad2d796b4f70`. The many working-tree deployment/audit files
are not included in that remote revision. No commit, push, reset or history rewrite was run.

After reviewing all existing and new changes locally, these commands include the
reviewed application/deployment files while keeping ignored credentials/data excluded:

```powershell
cd D:\CP-Assistant
git status --short
git add -- .gitignore .dockerignore .gitattributes .env.example .env.production.example Dockerfile compose.yaml compose.http-test.yaml gunicorn.conf.py requirements.txt README.md FINAL_AUDIT.md PROFILE_ASSISTANT_REPORT.md config core extension scripts templates deploy
git diff --cached --stat
git diff --cached --check
# Review the staged diff privately; never paste credential-bearing output.
git diff --cached
git commit -m "Audit production readiness and harden authentication"
git push origin main
```

Do not force-add ignored files. Only run the final two commands after the staged diff
has been reviewed. Do not force-push to remove history as part of this ordinary release.

## Changes requiring deployment

1. Rotate the exposed Groq key privately wherever used; this was not automated.
2. Compare the reviewed Compose file with the live working project/volume/environment;
   preserve its data and existing secrets. The requested CPU ceilings are now in source.
3. Deploy/rebuild web for the production engine safeguard, login-feed resilience and
   POST logout/template change. No schema migration is needed for these audit fixes.
4. Recreate web after changing environment values and reload Nginx after app recreation
   using the existing operating procedure. No fresh database initialization is needed.
5. Reload the extension for the backend-binding race fix. Its backend should remain
   `https://130-210-110-62.sslip.io`; reconnect only if the connection is expired/revoked.

The updated [README](README.md) and [deployment guide](deploy/README.md) provide the
setup, operation, extension, backup and troubleshooting details. No live deployment was made.
