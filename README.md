# 🚀 Algolytics

![Made with Python](https://img.shields.io/badge/Made%20with-Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Backend: Django](https://img.shields.io/badge/Backend-Django-092E20?style=for-the-badge&logo=django&logoColor=white)
![AI Engine: Groq](https://img.shields.io/badge/AI%20Engine-Groq-F55036?style=for-the-badge&logo=amd&logoColor=white)
![Containerized: Docker](https://img.shields.io/badge/Containerized-Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)

## 🌐 Live Application

The application is deployed using Docker with a persistent SQLite volume and automated cloud routing.

👉 **Live Application:** http://140.238.162.114/

---

An advanced **Analytics and AI-Driven Insights Platform** built strictly for Competitive Programmers. Unlike traditional profile trackers, Algolytics leverages Large Language Models to perform elite-level code reviews, run rival face-offs, track granular problem statistics, identify core algorithmic weaknesses, and generate personalized 4-week practice roadmaps based on historical Codeforces performance.

The backend is powered by **Django**, utilizing custom authentication, SQLite database persistence, and **Groq's Llama 3.3** for lightning-fast algorithmic reasoning and feedback generation.

---

## 🚀 App Architecture & Pages

### 🏠 Home Page (Public)
- **Centralized Contest Hub**: Consolidates and displays live and upcoming contests across major competitive programming networks:
  - Codeforces
  - CodeChef
  - LeetCode
  - AtCoder

### 📊 Profile Analytics Page (Authenticated)
- **📈 ML Rating Trajectory**: Uses a predictive machine learning model to evaluate submission trajectories, past contest ranks, and milestones to simulate upcoming performance bands and calculate a reliable forward-looking user rating prediction.
- **Problem Ratings Solved**: Visualizes a breakdown of problem difficulty levels handled successfully by the user.
- **Tags Solved**: Provides a comprehensive chart of solved algorithmic categories (e.g., Dynamic Programming, Greedy, Graphs, Math) to show overall expertise.

### 🎛️ Dashboard Page (Authenticated)
Acts as the central command center, offering direct entry points to three core deep-analytical tools:
1. **🤖 AI Code Review**
2. **⚔️ Rival Comparison**
3. **🔍 Weak-Spot Analytics**

---

## 🛠️ Feature Deep-Dive

### 🤖 AI Code Review
- **Input**: Provide the official Codeforces problem link along with your written C++ solution.
- **Mechanism**: Automatically fetches and parses the problem description and official contest tutorials using `BeautifulSoup4`.
- **Feedback**: The LLM evaluates your logic directly against the official tutorial to isolate edge cases, hidden integer overflows, optimization bottlenecks, or potential TLE (Time Limit Exceeded) conditions.

### ⚔️ Rival Comparison
- **Input**: Provide a rival's Codeforces handle.
- **Mechanism**: Extracts comparative profile datasets across platforms.
- **Feedback**: Generates an exhaustive AI-driven comparative analysis, cross-examines key development metrics, visualizes a side-by-side comparison of the total number of problems solved, and details structural advice on how to outpace your competitor.

### 🔍 Weak-Spot Analytics & 4-Week Roadmap
- **Mechanism**: Automatically scans the user's last 100 historical Codeforces submissions to isolate incorrect verdicts (`WA`, `TLE`, `RE`).
- **Feedback**: Groups failure patterns by direct algorithmic classifications and explicitly outputs a highly personalized, structured **4-Week Action Plan** targeting those identified vulnerabilities.

### 🐳 Production-Ready Deployment
- Full Dockerization utilizing `python:3.11-slim` to maintain low system memory utilization.
- Production-grade Gunicorn WSGI server with custom timeouts tailored for external API connections.
- Seamless static file streaming using WhiteNoise middleware.
- Persistent external volume mapping to prevent data loss during container rebuilding.

---

## 🧱 Tech Stack

| Layer | Technologies |
|---|---|
| **Frontend** | HTML, CSS, Bootstrap 5, Vanilla JavaScript |
| **Backend** | Python, Django 5.2 |
| **AI Engine** | Groq API (Llama-3.3-70B-Versatile) |
| **Database** | SQLite3 |
| **Scraping** | Requests, BeautifulSoup4 |
| **Deployment** | Docker, Gunicorn, WhiteNoise |

---

## 🗂️ Project Structure

```text
Algolytics/
│
├── config/
│   ├── __pycache__/
│   ├── __init__.py
│   ├── asgi.py
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
│
├── core/
│   ├── __pycache__/
│   ├── migrations/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── forms.py
│   ├── models.py
│   ├── tests.py
│   ├── urls.py
│   └── views.py
│
├── staticfiles/
│
├── templates/
│   ├── core/
│   │   ├── code_review.html
│   │   ├── compare.html
│   │   ├── dashboard.html
│   │   ├── home.html
│   │   ├── predict.html
│   │   ├── profile.html
│   │   ├── register.html
│   │   ├── update_profile.html
│   │   └── weak_spot.html
│   └── base.html
│
├── venv/
│
├── .dockerignore
├── .env
├── .env.example
├── .gitignore
├── db.sqlite3
├── Dockerfile
├── LICENSE
├── manage.py
├── README.md
└── requirements.txt
```

---


## 🧪 Local Setup

### 1. Clone Repository
```bash
git clone https://github.com/yashgupta1126/Algolytics.git
cd Algolytics
```

### 2. Create Virtual Environment
```bash
python -m venv venv
```
**Windows**
```bash
venv\Scripts\activate
```
**Linux / Mac**
```bash
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Create Environment File
Create a `.env` file in the root directory:
```env
AI_API_KEY=your_groq_api_key_here
AI_API_URL=https://api.groq.com/openai/v1/chat/completions
AI_MODEL_NAME=llama-3.3-70b-versatile

EMAIL_USER=your_email@gmail.com
EMAIL_PASS=your_gmail_app_password

DEBUG=True

SECRET_KEY=django-insecure-your-secret-key-here
```

### 5. Initialize Database
```bash
python manage.py makemigrations
python manage.py migrate
```

### 6. Create Admin User
```bash
python manage.py createsuperuser
```

### 7. Run Development Server
```bash
python manage.py runserver
```

👉 Visit: **http://127.0.0.1:8000**

---

## 🐳 Docker Deployment

### 1. Create Production Environment File
Set up your `.env` configuration as detailed above, but toggle production mode:
```env
DEBUG=False
```

### 2. Create Persistent Database File
**Linux / Mac**
```bash
touch db.sqlite3
```
**Windows**
```bash
type nul > db.sqlite3
```

### 3. Build Docker Image
```bash
docker build -t algolytics .
```

### 4. Run Container
**Linux / Mac**
```bash
docker run -d \
  -p 80:8000 \
  --env-file .env \
  -v $(pwd)/db.sqlite3:/app/db.sqlite3 \
  --name algolytics_live \
  algolytics
```
**Windows PowerShell**
```powershell
docker run -d `
  -p 80:8000 `
  --env-file .env `
  -v ${PWD}/db.sqlite3:/app/db.sqlite3 `
  --name algolytics_live `
  algolytics
```

### 5. Run Production Migrations
```bash
docker exec -it algolytics_live python manage.py migrate
```

### 6. Create Production Admin
```bash
docker exec -it algolytics_live python manage.py createsuperuser
```

### 7. Access Application
👉 **http://localhost**

---

## 🛡️ Admin Panel

Visit: `/admin`

Admin capabilities include managing active user listings, adjusting custom database objects, and updating or manually overstepping integrated user Codeforces handles.

---

## 📄 License

This project is licensed under the MIT License.

---

## 🤝 Contributions

Contributions are welcome! Feel free to fork the repository, open structural issues, or submit pull requests with design upgrades.

---

## 📝 Author

**Yash Gupta** | Mechanical Engineering, IIT Kharagpur

📧 Email: [yg291557@gmail.com](mailto:yg291557@gmail.com)