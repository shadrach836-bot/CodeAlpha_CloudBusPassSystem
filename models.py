from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Route(Base):
    __tablename__ = "routes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    origin: Mapped[str] = mapped_column(String(60))
    destination: Mapped[str] = mapped_column(String(60))
    distance_km: Mapped[int] = mapped_column(Integer)
    base_fare_cents: Mapped[int] = mapped_column(Integer)     # money is ALWAYS integer paise
    per_km_cents: Mapped[int] = mapped_column(Integer)


class Trip(Base):
    __tablename__ = "trips"
    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"), index=True)
    departs_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    capacity: Mapped[int] = mapped_column(Integer, default=40)


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    kind: Mapped[str] = mapped_column(String(8))               # SINGLE | PASS
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"))
    trip_id: Mapped[int | None] = mapped_column(ForeignKey("trips.id"), nullable=True)
    seat_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str] = mapped_column(String(10))
    passenger_name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(15), index=True)
    email: Mapped[str] = mapped_column(String(120))
    price_cents: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="CONFIRMED")   # CONFIRMED|USED|CANCELLED
    signature: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    payment_ref: Mapped[str] = mapped_column(String(24))
    refund_cents: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SeatAllocation(Base):
    """Composite primary key (trip_id, seat_no) makes double-booking IMPOSSIBLE at DB level."""
    __tablename__ = "seat_allocations"
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id"), primary_key=True)
    seat_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), unique=True)


class ScanLog(Base):
    """Audit trail of every ticket verification (helps detect theft / reuse attempts)."""
    __tablename__ = "scan_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str] = mapped_column(String(200), default="")
    scanned_at: Mapped[datetime] = mapped_column(DateTime)
