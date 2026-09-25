from pathlib import Path
import os
import secrets

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
EXPORT_DIR = DATA_DIR / "exports"
DB_PATH = DATA_DIR / "securityfill.db"

for d in (DATA_DIR, UPLOAD_DIR, KNOWLEDGE_DIR, EXPORT_DIR):
    d.mkdir(parents=True, exist_ok=True)

ENVIRONMENT = os.getenv("ENVIRONMENT", "dev").strip().lower()
IS_PRODUCTION = ENVIRONMENT in {"production", "prod"}

# Upload caps (bytes) enforced while streaming to disk.
MAX_KNOWLEDGE_UPLOAD_BYTES = int(os.getenv("MAX_KNOWLEDGE_UPLOAD_BYTES", 20 * 1024 * 1024))
MAX_QUESTIONNAIRE_UPLOAD_BYTES = int(os.getenv("MAX_QUESTIONNAIRE_UPLOAD_BYTES", 10 * 1024 * 1024))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

APP_NAME = "SecurityFill"
APP_TAGLINE = "AI-powered security questionnaire answers from your policies"
SESSION_COOKIE = "sf_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 14  # 14 days
SESSION_COOKIE_SECURE = (
    os.getenv("SESSION_COOKIE_SECURE", "1" if IS_PRODUCTION else "0").strip().lower()
    in {"1", "true", "yes", "on"}
)

_SECRET_PLACEHOLDERS = {
    "",
    "change-me-in-production",
    "dev-secret-change-me-in-production",
}
_configured_secret = os.getenv("APP_SECRET", "").strip()
if IS_PRODUCTION:
    if _configured_secret in _SECRET_PLACEHOLDERS:
        raise RuntimeError(
            "APP_SECRET must be set to a strong random value in production "
            "(e.g. `python -c \"import secrets; print(secrets.token_hex(32))\"`)."
        )
    APP_SECRET = _configured_secret
else:
    if _configured_secret in _SECRET_PLACEHOLDERS:
        # Ephemeral per-process secret: safe by default, but sessions do not
        # survive restarts. Set APP_SECRET explicitly for stable dev sessions.
        APP_SECRET = secrets.token_hex(32)
        print("[config] APP_SECRET not set — generated an ephemeral secret for this process.")
    else:
        APP_SECRET = _configured_secret

# Plans
PLAN_FREE = "free"
PLAN_PRO = "pro"
PLAN_LIMITS = {
    PLAN_FREE: {
        "max_docs": 5,
        "max_questionnaires_per_month": 3,
        "max_questions_per_qn": 50,
        "max_answer_library": 100,
    },
    PLAN_PRO: {
        "max_docs": 200,
        "max_questionnaires_per_month": 200,
        "max_questions_per_qn": 2000,
        "max_answer_library": 10000,
    },
}

# Stripe (optional — mock checkout when keys empty)
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
PRO_PRICE_DISPLAY = os.getenv("PRO_PRICE_DISPLAY", "$49/mo")

# Demo seed — local/demo only; forcibly disabled in production.
SEED_DEMO = os.getenv("SEED_DEMO", "1") == "1" and not IS_PRODUCTION
DEMO_EMAIL = os.getenv("DEMO_EMAIL", "demo@securityfill.local")
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "demo1234")
