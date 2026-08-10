# SecurityFill

AI-powered **security questionnaire auto-filler** — productized for indie SaaS teams.

**Full flow:** Register → Workspace → Upload policies → Import questionnaire → AI draft → Human review → Answer library → Export → (optional) Pro billing

## Features

| Area | Capability |
|------|------------|
| Auth | Register / login / logout, signed session cookies |
| Multi-tenant | Per-user Workspace isolation |
| Knowledge | PDF / TXT / MD / **DOCX**, chunk + retrieve |
| Questionnaires | CSV / XLSX import |
| AI answers | OpenAI-compatible LLM or offline keyword mode |
| Answer library | Reviewed answers reused on similar questions |
| Plans | Free limits + Pro (Stripe or mock upgrade) |
| Export | XLSX (confidence colors) / CSV |

## Quick start

```bash
cd security-fill
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open http://127.0.0.1:8000

**Demo account (seeded):** `demo@securityfill.local` / `demo1234` (Pro)

## Product flow (manual)

1. Register or login with demo  
2. Upload `samples/sample_security_policy.txt`  
3. Upload `samples/sample_questionnaire.csv`  
4. **一键生成全部答案**  
5. **审阅并入库** a few questions  
6. Upload the same questionnaire again → see **答案库** hits  
7. Export XLSX  
8. Pricing page → upgrade Pro (mock if no Stripe keys)

## Automated E2E

```bash
source .venv/bin/activate
python scripts/e2e_product_flow.py
```

## Configuration

| Env | Meaning |
|-----|---------|
| `OPENAI_API_KEY` | Enable LLM answers |
| `APP_SECRET` | Session signing secret |
| `STRIPE_*` | Real Checkout; empty = mock Pro upgrade |
| `SEED_DEMO` | Create demo user on startup |

### Free vs Pro limits

| | Free | Pro |
|--|------|-----|
| Knowledge docs | 5 | 200 |
| Questionnaires / month | 3 | 200 |
| Questions / questionnaire | 50 | 2000 |
| Answer library | 100 | 10000 |

## API (auth cookie required except health/auth)

- `POST /api/auth/register|login|logout` · `GET /api/auth/me`
- `GET/POST/DELETE /api/knowledge`
- `GET/POST /api/questionnaires` · generate · export
- `GET/POST/DELETE /api/library`
- `POST /api/billing/checkout` · webhook

## Stack

Python 3.12 · FastAPI · SQLAlchemy · SQLite · Jinja2 · openpyxl · pypdf · python-docx · Stripe SDK
