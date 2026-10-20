"""Cloud Bus Pass System - stateless REST API (any number of copies can run behind a load balancer)."""
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory
from sqlalchemy import func, select

import config
import services as svc
from db import make_engine, make_session_factory
from models import Base, Route, SeatAllocation, Trip
from seed import seed


class RateLimiter:
    """Per-IP sliding window (per process). In the cloud, put a WAF / API gateway limit in front too."""
    def __init__(self, limit, window=60):
        self.limit, self.window, self.hits, self.lock = limit, window, defaultdict(deque), threading.Lock()

    def allow(self, key):
        now = time.time()
        with self.lock:
            q = self.hits[key]
            while q and q[0] < now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


def create_app(overrides: dict | None = None):
    app = Flask(__name__, static_folder=None)
    app.config.update(DATABASE_URL=config.DATABASE_URL, SECRET_KEY=config.SECRET_KEY,
                      STAFF_KEY=config.STAFF_KEY, RATE_LIMIT_PER_MIN=config.RATE_LIMIT_PER_MIN)
    app.config.update(overrides or {})

    engine = make_engine(app.config["DATABASE_URL"])
    Session = make_session_factory(engine)
    for attempt in range(3):                       # several replicas may start at once; tolerate the race
        try:
            Base.metadata.create_all(engine)
            with Session() as s:
                seed(s)
            break
        except Exception:
            time.sleep(1 + attempt)
    limiter = RateLimiter(app.config["RATE_LIMIT_PER_MIN"])
    secret = app.config["SECRET_KEY"]

    def limited(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            ip = (request.headers.get("X-Forwarded-For", request.remote_addr) or "?").split(",")[0].strip()
            if not limiter.allow(ip):
                raise svc.ApiError(429, "rate_limited", "Too many requests - slow down")
            return fn(*a, **kw)
        return wrapper

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise svc.ApiError(400, "bad_request", "Send a JSON object")
        return data

    @app.errorhandler(svc.ApiError)
    def api_error(e):
        return jsonify(error=e.code, message=e.message), e.status

    @app.errorhandler(404)
    def nf(_):
        return jsonify(error="not_found", message="Not found"), 404

    @app.errorhandler(500)
    def err(_):
        return jsonify(error="server_error", message="Something went wrong, please retry"), 500

    # ---------- public pages / health ----------
    @app.get("/")
    def home():
        return send_from_directory(os.path.join(os.path.dirname(__file__), "static"), "index.html")

    @app.get("/health")
    def health():                                   # used by load balancer / Kubernetes probes
        with Session() as s:
            s.execute(select(1))
        return jsonify(status="ok")

    # ---------- catalogue ----------
    @app.get("/api/routes")
    def routes():
        with Session() as s:
            return jsonify([{"id": r.id, "code": r.code, "name": r.name, "origin": r.origin,
                             "destination": r.destination, "distance_km": r.distance_km}
                            for r in s.scalars(select(Route).order_by(Route.id))])

    @app.get("/api/routes/<int:rid>/trips")
    def trips(rid):
        day = request.args.get("date") or svc.utcnow().date().isoformat()
        try:
            start = datetime.fromisoformat(day)
        except ValueError:
            raise svc.ApiError(400, "bad_request", "date must be YYYY-MM-DD")
        with Session() as s:
            booked = dict(s.execute(select(SeatAllocation.trip_id, func.count()).group_by(SeatAllocation.trip_id)).all())
            rows = s.scalars(select(Trip).where(Trip.route_id == rid, Trip.departs_at >= start,
                                                Trip.departs_at < start + timedelta(days=1)).order_by(Trip.departs_at))
            now = svc.utcnow()
            return jsonify([{"id": t.id, "departs_at": t.departs_at.isoformat(timespec="minutes"),
                             "capacity": t.capacity, "seats_left": t.capacity - booked.get(t.id, 0),
                             "departed": t.departs_at <= now} for t in rows])

    @app.get("/api/trips/<int:tid>/seats")
    def seats(tid):
        with Session() as s:
            trip = s.get(Trip, tid)
            if not trip:
                raise svc.ApiError(404, "trip_not_found", "Trip not found")
            taken = sorted(s.scalars(select(SeatAllocation.seat_no).where(SeatAllocation.trip_id == tid)))
            return jsonify(trip_id=tid, capacity=trip.capacity, booked=taken)

    @app.post("/api/quote")
    def quote():
        with Session() as s:
            return jsonify(svc.quote(s, body()))

    # ---------- booking ----------
    @app.post("/api/book")
    @limited
    def book():
        key = (request.headers.get("Idempotency-Key") or "").strip()[:64] or None
        with Session() as s:
            t, replayed = svc.book(s, body(), key, secret)
            return jsonify(ticket=svc.ticket_view(s, t), replayed=replayed), (200 if replayed else 201)

    @app.post("/api/tickets/lookup")
    @limited
    def lookup():
        d = body()
        with Session() as s:
            return jsonify(ticket=svc.ticket_view(s, svc.get_owned_ticket(s, d.get("code"), d.get("phone"))))

    @app.post("/api/tickets/recover")
    @limited
    def recover():
        d = body()
        with Session() as s:
            return jsonify(tickets=svc.recover(s, d.get("phone"), d.get("email")))

    @app.post("/api/tickets/cancel")
    @limited
    def cancel():
        d = body()
        with Session() as s:
            t = svc.cancel(s, d.get("code"), d.get("phone"))
            return jsonify(ticket=svc.ticket_view(s, t), refund=f"₹{t.refund_cents / 100:.2f}")

    # ---------- staff boarding verification ----------
    @app.post("/api/verify")
    @limited
    def verify():
        if not svc.security.safe_eq(request.headers.get("X-Staff-Key", ""), app.config["STAFF_KEY"]):
            raise svc.ApiError(401, "unauthorized", "Valid staff key required")
        d = body()
        with Session() as s:
            return jsonify(svc.verify(s, d.get("token"), secret, d.get("trip_id"), d.get("route_id")))

    app.Session = Session
    app.engine = engine
    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=8000)
