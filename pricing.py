"""Server-side fare engine. The client can NEVER set the price - this is the single source of truth."""

CATEGORY_PCT = {"adult": 100, "student": 50, "senior": 60, "child": 50}
PASS_TYPES = {"DAY": (1, 200), "WEEK": (7, 800), "MONTH": (30, 2500)}   # (valid days, fare multiplier %)


def _round_50(x: int) -> int:                      # round to nearest 50 paise
    return ((x + 25) // 50) * 50


def price_cents(route, kind: str, category: str, pass_type: str | None = None) -> int:
    if category not in CATEGORY_PCT:
        raise ValueError("invalid passenger category")
    full = route.base_fare_cents + route.per_km_cents * route.distance_km
    if kind == "SINGLE":
        return _round_50(full * CATEGORY_PCT[category] // 100)
    if kind == "PASS":
        if pass_type not in PASS_TYPES:
            raise ValueError("invalid pass type")
        _, mult = PASS_TYPES[pass_type]
        return _round_50(full * mult // 100 * CATEGORY_PCT[category] // 100)
    raise ValueError("invalid ticket kind")


def rupees(cents: int) -> str:
    return f"₹{cents / 100:.2f}"
