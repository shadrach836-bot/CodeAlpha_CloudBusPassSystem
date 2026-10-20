"""Simulates a rush of passengers fighting for a few seats. Run against any deployment:
    python loadtest.py http://localhost:8000 300
Proves: no seat is ever sold twice, no request is lost, and shows throughput."""
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
N = int(sys.argv[2]) if len(sys.argv) > 2 else 200
SEATS = 15                                    # only 15 seats contested by N people


def call(path, body=None, headers=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def pick_trip():
    trips = call("/api/routes/2/trips?date=" + time.strftime("%Y-%m-%d", time.gmtime(time.time() + 86400)))[1]
    return next(t["id"] for t in trips if t["seats_left"] == t["capacity"])


trip = pick_trip()


def passenger(i):
    p = {"kind": "SINGLE", "route_id": 2, "trip_id": trip, "seat_no": (i % SEATS) + 1, "category": "adult",
         "name": f"Load User {i}", "phone": f"9{i:09d}", "email": f"u{i}@example.com"}
    return call("/api/book", p, {"Idempotency-Key": f"load-{trip}-{i}"})


start = time.time()
with ThreadPoolExecutor(max_workers=50) as ex:
    results = list(ex.map(passenger, range(N)))
secs = time.time() - start

codes = Counter(r[0] for r in results)
booked = call(f"/api/trips/{trip}/seats")[1]["booked"]
print(f"requests: {N}  time: {secs:.2f}s  throughput: {N / secs:.0f} req/s")
print("status codes:", dict(codes))
print(f"seats booked: {len(booked)} (expected {min(N, SEATS)}), unique: {len(set(booked))}")
ok = codes[201] == len(booked) == len(set(booked)) == min(N, SEATS) and set(codes) <= {201, 409}
print("RESULT:", "PASS - no double bookings, no lost requests" if ok else "FAIL")
sys.exit(0 if ok else 1)
