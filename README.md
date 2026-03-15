# Sklavounos HR

Production-ready v0.1 skeleton for a leave and staff management system using FastAPI, Jinja, Postgres, and Railway.

## Features in v0.1
- Admin login/logout
- Session-based authentication
- Postgres-ready SQLAlchemy setup
- Admin seed on first startup
- Dashboard summary cards
- Employees page placeholder
- Leave Types page placeholder
- Leave Requests page placeholder
- Railway-ready deployment config

## Local run
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

## Default login
The app auto-creates the first admin user from env vars:
- username: ADMIN_USER
- password: ADMIN_PASSWORD

## Environment variables
See `.env.example`.
