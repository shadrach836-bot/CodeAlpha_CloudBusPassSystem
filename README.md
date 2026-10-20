# CodeAlpha_CloudBusPassSystem

**CodeAlpha Cloud Computing Internship - Task 3: Cloud-Based Bus Pass System**

An online bus ticket and pass booking system built for the cloud. Tickets cannot be lost, stolen or mispriced,
seats cannot be double-sold, and the system adds servers automatically when traffic spikes.

## How each task requirement is met

| Task requirement | Implementation |
|---|---|
| Online ticket booking system hosted on the cloud | Flask REST API + booking web page (`static/index.html`), packaged with Docker, deployable on AWS / Azure / GCP |
| Prevent **ticket loss** | Tickets are stored durably in the database; **idempotency keys** make network retries return the same ticket instead of booking twice; lost codes can be **recovered** with phone + email |
| Prevent **ticket theft** | Every ticket is signed with **HMAC-SHA256**; lookup/cancel require code **and** owner's phone; a ticket can be boarded **only once** (atomic); only staff with a key can verify; scans are audit-logged; rate limiting on sensitive endpoints |
| Prevent **incorrect pricing** | Fares are computed **only on the server** from route + passenger type (client price is ignored); if the client's shown price is stale the booking is rejected (`price_changed`); price is inside the signature, so editing it in the DB invalidates the ticket; money is stored as integer paise (no rounding errors) |
| Handle high traffic by **dynamically provisioning servers** | Stateless app + shared PostgreSQL. `docker compose up --scale web=N` adds servers behind nginx live; `k8s/bus-booking.yaml` has a **Horizontal Pod Autoscaler** (2 to 20 servers at 60% CPU) |
| Scalability & reliability over traditional sites | No double-booking even under 300 concurrent requests (DB primary key on trip+seat), `/health` endpoint with auto-restart, connection pooling, safe retries |
| Test and deploy for seamless booking | 20 automated tests + a load test; Dockerfile, docker-compose and Kubernetes manifests; seat map UI with live availability |

## Architecture
```
 Passengers --> Load Balancer (nginx / cloud LB) --> [ web 1 ][ web 2 ] ... [ web N ]   <- autoscaled
                                                              |
                                                     PostgreSQL (shared)
```
The app servers keep no state, so any server can handle any request and new ones can be added at any time.

## Run locally (SQLite, no setup)
```bash
pip install -r requirements.txt
python app.py                    # open http://localhost:8000
pytest -q                        # 20 tests
```
Demo staff key for the "Boarding check" box: `staff-demo-key`.

## Run like production (3 servers + load balancer + PostgreSQL)
```bash
docker compose up --build -d          # open http://localhost
docker compose up -d --scale web=6    # traffic spike? add servers instantly
```

## Load test (proves no double booking under a rush)
```bash
python loadtest.py http://localhost:8000 300
# 300 people fight for 15 seats -> exactly 15 bookings, 285 clean "seat taken" replies
```

## Deploy to the cloud
- **Kubernetes (EKS / AKS / GKE):** push the image, edit `k8s/bus-booking.yaml`, `kubectl apply -f k8s/bus-booking.yaml`. The HPA handles dynamic provisioning.
- **AWS without Kubernetes:** ECS Fargate service (or EC2 Auto Scaling Group) behind an Application Load Balancer + Amazon RDS PostgreSQL. Set `DATABASE_URL`, `SECRET_KEY`, `STAFF_KEY` as environment variables. Add a target-tracking scaling policy on CPU 60%.
- **Render / Railway / Azure App Service:** deploy the Dockerfile, attach managed PostgreSQL, set the same environment variables.

## API summary
| Endpoint | Purpose |
|---|---|
| `GET /api/routes`, `GET /api/routes/<id>/trips?date=` | Browse routes and trips with seats left |
| `GET /api/trips/<id>/seats` | Seat map |
| `POST /api/quote` | Official fare for a route / passenger type / pass |
| `POST /api/book` (header `Idempotency-Key`) | Book a seat or a pass |
| `POST /api/tickets/lookup` / `recover` / `cancel` | Owner actions (need phone) |
| `POST /api/verify` (header `X-Staff-Key`) | Boarding validation |
| `GET /health` | Load balancer / Kubernetes probe |

## Ticket types and fares
Fare = (base 5.00 + 1.50 per km) x passenger factor: adult 100%, student 50%, senior 60%, child 50%.
Passes: day = 2x, week = 8x, month = 25x the single fare; unlimited rides on that route while valid.
Cancellation: single tickets up to 1 hour before departure, 90% refund.

## Project structure
```
app.py          API + rate limiter          services.py   booking / verify logic
models.py       DB tables + constraints     pricing.py    server-side fare engine
security.py     HMAC signing helpers        seed.py       demo routes and trips
db.py           SQLite / PostgreSQL engine  static/       booking web page
tests/          20 pytest tests             loadtest.py   concurrency / rush test
Dockerfile, docker-compose.yml, nginx.conf, k8s/bus-booking.yaml   <- cloud deployment
```

## Production notes
Set long random `SECRET_KEY` and `STAFF_KEY`; add real OTP/email verification and a payment gateway
(payment here is simulated); enable HTTPS at the load balancer; schedule database backups.
Times are in UTC.
