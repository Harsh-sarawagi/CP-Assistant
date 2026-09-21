# CP Assistant

CP Assistant is a Django-based competitive programming analytics platform with a Chrome Extension for Codeforces problemset pages.

The project provides:

- Codeforces profile and submission analytics
- Rating trajectory and solved-problem statistics
- Weak-tag analysis based on submission history
- AI-assisted code review using Groq
- Personalized practice roadmap generation
- Deterministic problem fit and tag-performance analysis
- Deterministic candidate filtering with an AI-selected next-problem recommendation
- An MV3 Chrome Extension with an inline panel on Codeforces problem pages

The extension is active only on URLs matching:

```text
https://codeforces.com/problemset/problem/{contestId}/{index}
```

Contest URLs under `/contest/` are not supported by the extension.

## Technology

| Area | Technology |
| --- | --- |
| Backend | Django 5.2 |
| Database | PostgreSQL |
| Frontend | Django templates, Bootstrap, vanilla JavaScript |
| Extension | Chrome Manifest V3, vanilla JavaScript |
| External data | Codeforces API and problem pages |
| AI | Groq-compatible API using `openai/gpt-oss-120b` |
| Deployment | Docker, Gunicorn, WhiteNoise |

## Project Structure

```text
CP-Assistant/
├── config/
│   ├── settings.py       Django configuration
│   ├── urls.py           Project URL routing
│   ├── asgi.py
│   └── wsgi.py
├── core/
│   ├── models.py         Custom user model
│   ├── forms.py          Authentication and application forms
│   ├── views.py          Web views, Codeforces services, AI, and extension API
│   ├── urls.py            Application routes
│   ├── tests.py          Backend tests
│   └── migrations/
├── extension/
│   ├── manifest.json
│   ├── background/
│   │   └── service-worker.js
│   ├── content/
│   │   └── codeforces-problem.js
│   ├── shared/
│   │   └── api.js
│   ├── options/
│   └── popup/
├── templates/
│   ├── base.html
│   └── core/
├── manage.py
├── requirements.txt
├── Dockerfile
├── .env.example
└── README.md
```

## Backend Features

### Codeforces analytics

The backend uses Codeforces user rating and submission APIs to calculate:

- Current rating and rating trend
- Predicted near-term rating values
- Solved-problem rating distribution
- Solved-problem tag distribution
- Exact submission history for a problem

Codeforces responses are cached where appropriate to reduce repeated requests.

### Problem analysis

For a current problem, the extension API returns deterministic analysis based on the problem rating, tags, and the user's submission history:

- Fit classification: `too_easy`, `good_practice`, `stretch`, or `too_hard`
- Per-tag attempted, solved, failed, and success-rate values
- Exact problem history and verdict sequence

### Recommendations

Recommendation candidates are retrieved from the Codeforces structured problem API. The backend excludes the current, attempted, and solved problems, then ranks candidates by tag relevance, weak-tag success rate, rating proximity, and reasonable difficulty progression.

The top candidates are supplied to Groq, which selects one candidate. The backend validates the result and falls back to the highest deterministic candidate if the response is invalid. Recommendation results are cached briefly.

### AI code review

The code-review page accepts a Codeforces problem URL and source code. The backend fetches the problem statement and available tutorial content, then sends the review prompt to the configured Groq-compatible API.

AI credentials remain on the backend and are never included in the Chrome Extension.

## Extension

The Chrome Extension uses Manifest V3 and is loaded as an unpacked extension during development.

On supported Codeforces problemset pages it:

1. Detects the contest ID and problem index.
2. Requests `/api/extension/context/?contest_id={contestId}&index={index}`.
3. Displays fit, rating, history, tag performance, and recommendation data in an inline panel.
4. Links directly to the recommended Codeforces problem.

The extension does not inject into contest pages.

## Local Setup

### 1. Create and activate a virtual environment

```powershell
python -m venv .venv
.venv\Scripts\activate
```

On Linux or macOS:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Copy `.env.example` to `.env` and set real local values. Do not commit `.env`.

Required configuration includes:

```env
DJANGO_SECRET_KEY=replace-with-a-long-random-secret
ALLOWED_HOSTS=127.0.0.1,localhost
EXTENSION_ALLOWED_ORIGIN=chrome-extension://your-extension-id

DB_NAME=your_database_name
DB_USER=your_database_user
DB_PASSWORD=your_database_password
DB_HOST=localhost
DB_PORT=5432

AI_API_KEY=your_groq_api_key
AI_API_URL=https://api.groq.com/openai/v1/chat/completions
AI_MODEL_NAME=openai/gpt-oss-120b
```

Do not place real secrets in `.env.example` or source files.

### 4. Initialize the database

```bash
python manage.py migrate
```

Create an administrative user when needed:

```bash
python manage.py createsuperuser
```

### 5. Run the development server

```bash
python manage.py runserver
```

The application is available at `http://127.0.0.1:8000`.

## Load the Extension Locally

1. Open `chrome://extensions`.
2. Enable Developer mode.
3. Select Load unpacked.
4. Choose the repository's `extension/` directory.
5. Reload the extension after changing extension files.

Log in to the Django application, then open a supported Codeforces problemset page.

## Extension API

```text
GET /api/extension/context/?contest_id={contestId}&index={index}
```

The authenticated response includes:

- `problem`
- `problem_history`
- `problem_analysis`
- `recommendation`
- Existing user analytics and weak-tag fields

Invalid problem identifiers and contest-style URLs are rejected.

## Tests and Checks

Run the backend tests:

```bash
python manage.py check
python manage.py test
```

Compile Python files when needed:

```bash
python -m py_compile config/settings.py core/views.py core/tests.py
```

Validate extension JavaScript:

```powershell
node --check extension\background\service-worker.js
node --check extension\content\codeforces-problem.js
node --check extension\shared\api.js
node --check extension\popup\popup.js
node --check extension\options\options.js
```

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
