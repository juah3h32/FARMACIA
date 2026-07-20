"""Headless API-only launcher — local dev, no desktop UI."""
from app.database.connection import init_db
from app.api.server import start_api_server
import app.config as cfg

init_db()
cfg.API_PORT = 8000
print(f"[dev] API arrancando en http://127.0.0.1:{cfg.API_PORT}")
start_api_server()
