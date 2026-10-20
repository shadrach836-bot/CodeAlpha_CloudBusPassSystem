"""Ticket anti-theft / anti-tamper helpers (HMAC-SHA256 signatures)."""
import hashlib
import hmac
import re
import secrets


def new_code() -> str:
    return "BP" + secrets.token_hex(5).upper()


def normalise_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 10 else ""


def sign(secret: str, t) -> str:
    """Signature covers every field that matters: change the price/seat/phone/dates in the
    database and the signature no longer matches, so the ticket is rejected at boarding."""
    payload = "|".join(str(x) for x in (
        t.code, t.kind, t.route_id, t.trip_id or 0, t.seat_no or 0, t.price_cents,
        t.category, t.phone, t.valid_from, t.valid_until))
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def safe_eq(a: str, b: str) -> bool:
    return hmac.compare_digest((a or "").encode(), (b or "").encode())
