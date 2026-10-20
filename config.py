import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///busbooking.db")
if DATABASE_URL.startswith("postgres://"):                 # Heroku/Render style URL
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

# Secret used to sign tickets (HMAC). MUST be set to a long random value in production.
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
# Key that bus conductors / gate scanners use to validate tickets.
STAFF_KEY = os.environ.get("STAFF_KEY", "staff-demo-key")
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "60"))
