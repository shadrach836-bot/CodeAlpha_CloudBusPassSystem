from datetime import datetime, time, timedelta

from sqlalchemy import select

from models import Route, Trip
from services import utcnow

ROUTES = [
    ("R101", "Central Station - Tech Park", "Central Station", "Tech Park", 12),
    ("R202", "City Centre - Airport", "City Centre", "Airport", 28),
    ("R303", "University - Old Town", "University", "Old Town", 7),
]
DEPARTURES = [6, 9, 12, 15, 18, 21]


def seed(session, days: int = 5):
    if session.scalar(select(Route.id).limit(1)):
        return
    today = utcnow().date()
    for code, name, o, d, km in ROUTES:
        r = Route(code=code, name=name, origin=o, destination=d, distance_km=km,
                  base_fare_cents=500, per_km_cents=150)
        session.add(r)
        session.flush()
        for day in range(days):
            for h in DEPARTURES:
                session.add(Trip(route_id=r.id, departs_at=datetime.combine(today + timedelta(days=day), time(h)), capacity=40))
    session.commit()
