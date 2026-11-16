# CP Assistant ? Codeforces Profile Analytics

Django 5.2 + PostgreSQL with a Manifest V3 Chrome extension. The extension runs only at
`https://codeforces.com/profile/{handle}`. It no longer injects on problem or contest pages.

## Features

- Public deterministic profile summaries, rating history/regression estimates, distinct
  solved-by-rating charts (including unrated), and multi-tag topic performance.
- Explainable weakness scores with minimum evidence thresholds, final verdict breakdowns,
  repeated-attempt patterns, and focus topics. Pending submissions are not failures.
- Deterministic practice candidates: solved exclusion, unseen preference, topic diversity,
  hard difficulty bounds, and a documented unrated fallback. No AI is needed for these.
- An optional, authenticated **Generate AI Improvement Plan** button. No automatic Groq calls.
- Private personal notes shared between extension and website: create, edit, delete,
  search, topic filter, and latest-update sorting.
- Website login/registration/profile settings and rating graphs remain available. The new
  dashboard links analytics, structured AI code review, the notebook and extension connections.
- Code review shows a monospace problem statement, highlighted original lines, specific
  suggestions, focus topics and a complete suggested solution. All generated text is escaped.
- Other profiles show Overview only. Weaknesses, Practice and Notes appear only on the
  connected account's saved Codeforces profile (case-insensitive handle match).

## Local setup

Use the existing virtual environment, or install the pinned `requirements.txt` in a new one.
Keep secrets in your ignored local `.env`; never commit them. Required variables:

```env
DJANGO_SECRET_KEY=your-long-random-secret
DB_NAME=your-existing-database
DB_USER=your-existing-user
DB_PASSWORD=your-existing-password
DB_HOST=localhost
DB_PORT=5432
ALLOWED_HOSTS=127.0.0.1,localhost
AI_API_KEY=your-key
AI_API_URL=https://api.groq.com/openai/v1/chat/completions
AI_MODEL_NAME=openai/gpt-oss-120b
EXTENSION_ALLOWED_ORIGIN=chrome-extension://your-actual-32-letter-extension-id
```

Replace the extension ID placeholder. An optional `EXTENSION_ALLOWED_IDS` comma-separated
list permits multiple explicit client IDs. The single origin above is also used to derive
an allowed ID. Arbitrary redirect destinations and wildcard credentialed CORS are not accepted.

```powershell
.\.venv\Scripts\python.exe -B manage.py migrate
.\.venv\Scripts\python.exe -B manage.py collectstatic --noinput
.\.venv\Scripts\python.exe -B manage.py runserver
```

The new additive migration copies historical problem notes into the personal notebook
and leaves the original records intact. Do not reset the database or delete SQLite backups.

## Extension setup and connection

1. Load `extension/` unpacked at `chrome://extensions` in Developer mode; review permissions.
2. Copy its ID into the allowlist above and restart Django after editing `.env`.
3. In extension options, configure the backend origin. HTTP is permitted only for loopback
   development; HTTPS is required elsewhere. Grant the backend host permission if prompted.
4. Open any Codeforces profile. Overview loads without login, with vertical solved-by-rating
   bars and a topic pie chart. Topic shares count solved-topic assignments because tags overlap.
5. Click Connect Account, use the existing Django login/registration, then explicitly approve
   the extension. The background worker completes PKCE authorization and stores credentials
   in storage restricted to trusted extension contexts. Codeforces page scripts receive no tokens.
6. Valid authorization restores after worker/browser restarts. Access lasts 10 minutes;
   rotating renewal is available until the 30-day grant expires or is revoked. Refresh reuse
   revokes the entire grant. Disconnect in the extension or revoke on `/extension/connections/`.

Website logout ends its cookie session; extension authorizations are independent. Viewing
another Codeforces profile changes public analytics and hides the personal tabs; it does not
change the connected Django account or notebook ownership. Save your handle in profile settings
to show your personal tabs on that profile. This is a display rule, not proof of Codeforces ownership.
Changing backend clears local authorization and never forwards old tokens to the new host;
revoke the old grant on the old website if needed.

## Website

`/profile/` uses the same analytics as the extension. `/notes/` is the shared private notebook.
`/ai-review/` provides structured code feedback and full suggested code. The separate
Weak-Spot website tool has been retired; old `/weak-spot/` bookmarks redirect to `/profile/`
without making an AI request. Shared analytics and extension practice algorithms are unchanged.
Regression predictions are labeled estimates; topic counts overlap across tags.

## Data accuracy and limits

Profile bundles cache for 5 minutes (30 seconds when practice data fails), the problem pool
for 6 hours. One user.status response is reused across all analytics tabs. At least 10,000
returned submissions is conservatively marked potentially truncated; raw histories are not
returned by the public analytics endpoint. Missing stable IDs are also disclosed. Practice
recommendations are withheld for incomplete histories so older solved problems are not
incorrectly presented as unseen.

Weakness classification requires 5 distinct judged problems and 8 final submissions per tag.
Score: 65% unsolved-problem rate + 20% unsuccessful-submission rate + 15% repeated-unsuccessful
signal (unsolved problems with 3+ final attempts). Low samples are not labeled weak.
Average attempts per solved problem counts all observed final submissions on solved problems.
Verdicts never establish a particular coding root cause.

Rated practice bounds are current rating ?200, with an 800 minimum and a 1000 upper-bound
floor for very low ratings. Unrated profiles use observed median attempted difficulty,
clamped to 800?1400; empty histories start at 800?1000. Lists are deduplicated and stable
within a cached bundle; attempted unsolved problems fill gaps only after unseen candidates.
AI improvement plans are limited in PostgreSQL to 3 attempts/hour/account and one active
request. Successful identical summaries are cached for 15 minutes. Generated text is
rendered safely; no provider secrets or raw submission histories are sent to the UI.

## APIs, security, and verification

See [extension setup](extension/README.md) and the [implementation report](PROFILE_ASSISTANT_REPORT.md)
for the endpoint table, token lifecycle, baseline results, limitations, and precise Chrome checks.

```powershell
.\.venv\Scripts\python.exe -B manage.py check
.\.venv\Scripts\python.exe -B manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe -B scripts/verify_project.py
.\.venv\Scripts\python.exe -B scripts/verify_project.py --postgres
node --test extension/tests/extension.test.cjs scripts/tests/code-review.test.cjs
```

The runner blocks all external HTTP. `--postgres` runs Django TestCase transactions against
existing PostgreSQL without creating/dropping a database or flushing tables. Records roll
back, and table fingerprints are compared before/after. PostgreSQL sequences can advance.
Avoid concurrent user edits during the comparison. No live paid inference is part of the tests.

## Docker Deployment

The project includes a Dockerfile that installs the Python dependencies, collects static files, and runs Django with Gunicorn on port 8000.

Build the image:

```bash
docker build -t cp-assistant .
```

Run it with a production environment file:

```bash
docker run -d \
  -p 80:8000 \
  --env-file .env \
  --name cp-assistant \
  cp-assistant
```

Run migrations inside the container:

```bash
docker exec -it cp-assistant python manage.py migrate
```
