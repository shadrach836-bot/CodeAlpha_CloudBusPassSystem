"""Business logic: booking, lookup, recovery, cancellation, boarding verification."""
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

import pricing
import security
from models import Route, ScanLog, SeatAllocation, Ticket, Trip

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
REFUND_PCT = 90
CANCEL_CUTOFF = timedelta(hours=1)


class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ticket_view(session, t) -> dict:
    route = session.get(Route, t.route_id)
    trip = session.get(Trip, t.trip_id) if t.trip_id else None
    return {
        "code": t.code, "token": f"{t.code}.{t.signature}", "kind": t.kind, "status": t.status,
        "route": {"code": route.code, "name": route.name, "origin": route.origin, "destination": route.destination},
        "trip_id": t.trip_id, "departs_at": trip.departs_at.isoformat(timespec="minutes") if trip else None,
        "seat_no": t.seat_no, "category": t.category, "passenger_name": t.passenger_name,
        "phone_masked": "XXXXXX" + t.phone[-4:], "price_cents": t.price_cents,
        "price": pricing.rupees(t.price_cents), "valid_from": t.valid_from.isoformat(),
        "valid_until": t.valid_until.isoformat(), "refund_cents": t.refund_cents,
        "payment_ref": t.payment_ref,
    }


def quote(session, p: dict) -> dict:
    route = session.get(Route, p.get("route_id"))
    if not route:
        raise ApiError(404, "route_not_found", "Route not found")
    try:
        cents = pricing.price_cents(route, (p.get("kind") or "SINGLE").upper(),
                                    (p.get("category") or "adult").lower(),
                                    (p.get("pass_type") or "").upper() or None)
    except ValueError as e:
        raise ApiError(400, "bad_request", str(e))
    return {"price_cents": cents, "price": pricing.rupees(cents)}


def book(session, p: dict, idem_key: str | None, secret: str):
    """Returns (ticket, replayed). Atomic: either the ticket + seat are both saved, or neither."""
    phone = security.normalise_phone(p.get("phone"))
    if idem_key:
        old = session.scalar(select(Ticket).where(Ticket.idempotency_key == idem_key))
        if old:                                                   # retry after network loss -> same ticket
            if old.phone != phone:
                raise ApiError(409, "idempotency_conflict", "Idempotency-Key already used")
            return old, True

    name = (p.get("name") or "").strip()
    email = (p.get("email") or "").strip().lower()
    kind = (p.get("kind") or "SINGLE").upper()
    category = (p.get("category") or "adult").lower()
    if len(name) < 2 or len(name) > 80:
        raise ApiError(400, "bad_request", "Passenger name must be 2-80 characters")
    if not phone:
        raise ApiError(400, "bad_request", "A valid 10-digit phone number is required")
    if not EMAIL_RE.match(email):
        raise ApiError(400, "bad_request", "A valid email is required")

    route = session.get(Route, p.get("route_id"))
    if not route:
        raise ApiError(404, "route_not_found", "Route not found")
    pass_type = (p.get("pass_type") or "").upper() or None
    try:
        price = pricing.price_cents(route, kind, category, pass_type)   # server decides the price
    except ValueError as e:
        raise ApiError(400, "bad_request", str(e))
    expected = p.get("expected_price_cents")
    if expected is not None and expected != price:
        raise ApiError(409, "price_changed", f"Price is {pricing.rupees(price)}, not what you were shown. Refresh and retry.")

    trip_id = seat_no = None
    if kind == "SINGLE":
        trip = session.get(Trip, p.get("trip_id"))
        if not trip or trip.route_id != route.id:
            raise ApiError(404, "trip_not_found", "Trip not found for this route")
        if trip.departs_at <= utcnow():
            raise ApiError(409, "trip_departed", "This trip has already departed")
        seat_no = p.get("seat_no")
        if not isinstance(seat_no, int) or not 1 <= seat_no <= trip.capacity:
            raise ApiError(400, "bad_request", f"Seat must be between 1 and {trip.capacity}")
        trip_id = trip.id
        valid_from = valid_until = trip.departs_at.date()
    else:
        try:
            start = date.fromisoformat(p.get("start_date") or utcnow().date().isoformat())
        except ValueError:
            raise ApiError(400, "bad_request", "start_date must be YYYY-MM-DD")
        if start < utcnow().date():
            raise ApiError(400, "bad_request", "Pass cannot start in the past")
        valid_from, valid_until = start, start + timedelta(days=pricing.PASS_TYPES[pass_type][0] - 1)

    t = Ticket(code=security.new_code(), kind=kind, route_id=route.id, trip_id=trip_id, seat_no=seat_no,
               category=category, passenger_name=name, phone=phone, email=email, price_cents=price,
               valid_from=valid_from, valid_until=valid_until, status="CONFIRMED", signature="",
               idempotency_key=idem_key or None, payment_ref="PAY" + uuid.uuid4().hex[:12].upper(),
               created_at=utcnow())
    try:
        session.add(t)
        session.flush()
        if kind == "SINGLE":
            session.add(SeatAllocation(trip_id=trip_id, seat_no=seat_no, ticket_id=t.id))
            session.flush()                                     # PK clash here = seat already taken
        t.signature = security.sign(secret, t)
        session.commit()
    except IntegrityError:
        session.rollback()
        if idem_key:                                            # two identical retries raced each other
            again = session.scalar(select(Ticket).where(Ticket.idempotency_key == idem_key))
            if again:
                return again, True
        raise ApiError(409, "seat_taken", f"Seat {seat_no} is already booked. Please choose another seat.")
    return t, False


def get_owned_ticket(session, code, phone):
    """Ticket + phone must both match. Same error either way, so codes cannot be enumerated."""
    t = session.scalar(select(Ticket).where(Ticket.code == (code or "").strip().upper()))
    p = security.normalise_phone(phone)
    if not t or not p or not security.safe_eq(t.phone, p):
        raise ApiError(404, "ticket_not_found", "No ticket matches that code and phone number")
    return t


def recover(session, phone, email):
    p, e = security.normalise_phone(phone), (email or "").strip().lower()
    if not p or not e:
        return []
    rows = session.scalars(select(Ticket).where(Ticket.phone == p, Ticket.email == e)
                           .order_by(Ticket.id.desc()).limit(50)).all()
    return [ticket_view(session, t) for t in rows]


def cancel(session, code, phone):
    t = get_owned_ticket(session, code, phone)
    if t.kind != "SINGLE":
        raise ApiError(409, "not_cancellable", "Passes cannot be cancelled")
    if t.status != "CONFIRMED":
        raise ApiError(409, "not_cancellable", f"Ticket is already {t.status}")
    trip = session.get(Trip, t.trip_id)
    if trip.departs_at - utcnow() < CANCEL_CUTOFF:
        raise ApiError(409, "too_late", "Tickets can only be cancelled up to 1 hour before departure")
    t.status, t.refund_cents = "CANCELLED", t.price_cents * REFUND_PCT // 100
    session.execute(delete(SeatAllocation).where(SeatAllocation.ticket_id == t.id))   # seat is free again
    session.commit()
    return t


def verify(session, token, secret, trip_id=None, route_id=None) -> dict:
    """Boarding check. Marks a SINGLE ticket USED atomically, so it can only ever be used once."""
    now = utcnow()
    code, _, sig = (token or "").partition(".")
    t = session.scalar(select(Ticket).where(Ticket.code == code))

    def done(valid, result, detail=""):
        session.add(ScanLog(ticket_id=t.id if t else None, result=result, detail=detail[:200], scanned_at=now))
        session.commit()
        return {"valid": valid, "result": result, "detail": detail,
                "ticket": ticket_view(session, t) if t else None}

    if not t:
        return done(False, "UNKNOWN_TICKET", "No such ticket")
    expected = security.sign(secret, t)
    if not (security.safe_eq(sig, expected) and security.safe_eq(t.signature, expected)):
        return done(False, "TAMPERED", "Signature mismatch - ticket data was altered or forged")
    if t.status == "CANCELLED":
        return done(False, "CANCELLED", "Ticket was cancelled")
    if t.status == "USED":
        return done(False, "ALREADY_USED", f"Ticket already used at {t.used_at}")
    if route_id and t.route_id != route_id:
        return done(False, "WRONG_ROUTE", "Ticket is for a different route")
    if t.kind == "SINGLE":
        if trip_id and t.trip_id != trip_id:
            return done(False, "WRONG_TRIP", "Ticket is for a different trip")
        r = session.execute(update(Ticket).where(Ticket.id == t.id, Ticket.status == "CONFIRMED")
                            .values(status="USED", used_at=now))
        if r.rowcount != 1:                                     # someone else scanned it first
            session.rollback()
            return done(False, "ALREADY_USED", "Ticket already used")
        t.status, t.used_at = "USED", now
        return done(True, "VALID", "Boarding approved")
    today = now.date()                                          # PASS: unlimited rides inside validity
    if today < t.valid_from:
        return done(False, "NOT_YET_VALID", f"Pass starts on {t.valid_from}")
    if today > t.valid_until:
        return done(False, "EXPIRED", f"Pass expired on {t.valid_until}")
    return done(True, "VALID", "Pass accepted")
