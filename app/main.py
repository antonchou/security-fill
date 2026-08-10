from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.auth import read_session_token
from app.config import (
    APP_NAME,
    APP_TAGLINE,
    DEMO_EMAIL,
    DEMO_PASSWORD,
    PRO_PRICE_DISPLAY,
    SESSION_COOKIE,
)
from app.database import SessionLocal, User, init_db
from app.routers.api import router as api_router
from app.routers.auth_routes import router as auth_router
from app.routers.billing import router as billing_router
from app.services.llm import has_llm
from app.services.seed import ensure_demo_user

BASE = Path(__file__).resolve().parent

app = FastAPI(title=APP_NAME, version="1.0.0")
app.include_router(api_router)
app.include_router(auth_router)
app.include_router(billing_router)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))


@app.on_event("startup")
def on_startup():
    init_db()
    ensure_demo_user()


def _page_ctx(request: Request, **extra):
    user = None
    db = SessionLocal()
    try:
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            uid = read_session_token(token)
            if uid:
                user = db.get(User, uid)
        return {
            "request": request,
            "app_name": APP_NAME,
            "tagline": APP_TAGLINE,
            "llm_enabled": has_llm(),
            "user": user,
            "demo_email": DEMO_EMAIL,
            "demo_password": DEMO_PASSWORD,
            "pro_price": PRO_PRICE_DISPLAY,
            **extra,
        }
    finally:
        db.close()


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token and read_session_token(token):
        return RedirectResponse("/app", status_code=302)
    return templates.TemplateResponse(request, "landing.html", _page_ctx(request))


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", _page_ctx(request))


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html", _page_ctx(request))


@app.get("/pricing", response_class=HTMLResponse)
def pricing_page(request: Request):
    return templates.TemplateResponse(request, "pricing.html", _page_ctx(request))


@app.get("/app", response_class=HTMLResponse)
def app_home(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token or not read_session_token(token):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(request, "index.html", _page_ctx(request))


@app.get("/app/library", response_class=HTMLResponse)
def library_page(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token or not read_session_token(token):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(request, "library.html", _page_ctx(request))


@app.get("/q/{qn_id}", response_class=HTMLResponse)
def review_page(request: Request, qn_id: int):
    token = request.cookies.get(SESSION_COOKIE)
    if not token or not read_session_token(token):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request, "review.html", _page_ctx(request, qn_id=qn_id)
    )
