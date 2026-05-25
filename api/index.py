from app.database.connection import init_db
from app.api.server import app  # noqa: F401 — Vercel busca `app` en este modulo

init_db()
