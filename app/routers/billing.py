"""Stripe billing with mock fallback when keys are not configured."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import AuthDep
from app.config import (
    PLAN_PRO,
    PRO_PRICE_DISPLAY,
    PUBLIC_BASE_URL,
    STRIPE_PRICE_ID,
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
)
from app.database import User, get_db

router = APIRouter(prefix="/api/billing", tags=["billing"])


def stripe_enabled() -> bool:
    return bool(STRIPE_SECRET_KEY and STRIPE_PRICE_ID)


@router.get("/status")
def billing_status(auth: AuthDep):
    return {
        "plan": auth.user.plan,
        "stripe_enabled": stripe_enabled(),
        "price_display": PRO_PRICE_DISPLAY,
        "stripe_customer_id": auth.user.stripe_customer_id or None,
    }


@router.post("/checkout")
def create_checkout(auth: AuthDep, db: Session = Depends(get_db)):
    """Start Pro upgrade. Uses Stripe Checkout when configured, else mock upgrade."""
    if auth.user.plan == PLAN_PRO:
        return {"ok": True, "already_pro": True, "url": f"{PUBLIC_BASE_URL}/app?upgraded=1"}

    if not stripe_enabled():
        # Mock: instant upgrade for local product demos
        auth.user.plan = PLAN_PRO
        db.commit()
        return {
            "ok": True,
            "mock": True,
            "url": f"{PUBLIC_BASE_URL}/app?upgraded=1",
            "message": "Mock billing: upgraded to Pro (no Stripe keys configured).",
        }

    import stripe

    stripe.api_key = STRIPE_SECRET_KEY
    try:
        if not auth.user.stripe_customer_id:
            customer = stripe.Customer.create(
                email=auth.user.email,
                name=auth.user.name or auth.user.email,
                metadata={"user_id": str(auth.user.id)},
            )
            auth.user.stripe_customer_id = customer["id"]
            db.commit()

        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=auth.user.stripe_customer_id,
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            success_url=f"{PUBLIC_BASE_URL}/app?upgraded=1",
            cancel_url=f"{PUBLIC_BASE_URL}/pricing?canceled=1",
            metadata={"user_id": str(auth.user.id)},
        )
        return {"ok": True, "url": session.url, "mock": False}
    except Exception as e:
        raise HTTPException(500, f"Stripe error: {e}") from e


@router.post("/mock-upgrade")
def mock_upgrade(auth: AuthDep, db: Session = Depends(get_db)):
    """Explicit mock upgrade endpoint for demos / e2e tests.

    Only available when real Stripe billing is NOT configured — otherwise it
    would let any signed-in user grant themselves Pro without paying.
    """
    if stripe_enabled():
        raise HTTPException(403, "Mock billing is disabled while Stripe is configured.")
    auth.user.plan = PLAN_PRO
    db.commit()
    return {"ok": True, "plan": PLAN_PRO}


@router.post("/mock-downgrade")
def mock_downgrade(auth: AuthDep, db: Session = Depends(get_db)):
    if stripe_enabled():
        raise HTTPException(403, "Mock billing is disabled while Stripe is configured.")
    auth.user.plan = "free"
    auth.user.stripe_subscription_id = ""
    db.commit()
    return {"ok": True, "plan": "free"}


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    if not stripe_enabled():
        raise HTTPException(400, "Stripe not configured")
    import stripe

    stripe.api_key = STRIPE_SECRET_KEY
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(400, f"Webhook error: {e}") from e

    etype = event["type"]
    data = event["data"]["object"]

    if etype == "checkout.session.completed":
        uid = (data.get("metadata") or {}).get("user_id")
        if uid:
            user = db.get(User, int(uid))
            if user:
                user.plan = PLAN_PRO
                user.stripe_customer_id = data.get("customer") or user.stripe_customer_id
                user.stripe_subscription_id = data.get("subscription") or ""
                db.commit()
    elif etype in {"customer.subscription.deleted", "customer.subscription.paused"}:
        cust = data.get("customer")
        if cust:
            user = db.query(User).filter(User.stripe_customer_id == cust).first()
            if user:
                user.plan = "free"
                user.stripe_subscription_id = ""
                db.commit()

    return {"received": True}
