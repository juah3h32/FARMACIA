from pathlib import Path
import os
import sys

APP_NAME = "Farmacia Eben-Ezer"
VERSION = "1.1.1"
PHARMACY_NAME = "FARMACIA EBEN-EZER"
PHARMACY_ADDRESS = "DirecciÃ³n de la farmacia"
PHARMACY_PHONE = "Tel: 000-000-0000"
PHARMACY_RFC = "RFC: XXXX000000XX0"

BASE_DIR = Path(__file__).parent.parent

# En EXE (PyInstaller frozen): guarda datos en %APPDATA%\FarmaciaEbenEzer\
# En desarrollo (script): guarda en /data/ junto al proyecto
if getattr(sys, 'frozen', False):
    DATA_DIR = Path(os.getenv('APPDATA', Path.home())) / "FarmaciaEbenEzer"
else:
    DATA_DIR = BASE_DIR / "data"

DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "farmacia.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

# â”€â”€ Secret key â€” auto-generated per installation, never hardcoded â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_key_file = DATA_DIR / "secret.key"
if _key_file.exists():
    SECRET_KEY = _key_file.read_text().strip()
else:
    import secrets as _secrets
    SECRET_KEY = _secrets.token_hex(32)
    _key_file.write_text(SECRET_KEY)

# â”€â”€ Turso (LibSQL) cloud DB â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Keep these private â€” do NOT commit to public repositories.
TURSO_DATABASE_URL = "libsql://farmacia-juanpa.aws-us-east-1.turso.io"
TURSO_AUTH_TOKEN   = (
    "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9"
    ".eyJhIjoicnciLCJpYXQiOjE3NzkxNTUwOTQsImlkIjoiMDE5ZTNkZTctZjQwMS03NmViLWFkYjgtZTRkMzAxZGExMTdjIiwicmlkIjoiNDVkNDAzNjItNzg4Ni00MDViLWE0Y2QtNDUxMjY1YTgxMzQ0In0"
    ".B3nY0-9gzbXkqNlj8MlzBjw44JP9OpVrG9QGrdx_tkB19QF8l7f5IgYoW3mLjOqUq4sTOVNQu78GEJMaVA0sDg"
)
# USE_TURSO=False â†’ local SQLite primary; TURSO_SYNC=True â†’ background backup to Turso
USE_TURSO   = False
TURSO_SYNC  = True

API_HOST = "127.0.0.1"
API_PORT = 8000
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 8

TAX_RATE = 0.16  # IVA 16% Mexico
CURRENCY_SYMBOL = "$"
LOW_STOCK_THRESHOLD = 10  # Alerta cuando stock <= este numero
EXPIRY_ALERT_DAYS = 30    # Alerta cuando vence en <= dias

SIDEBAR_WIDTH = 230
WINDOW_WIDTH = 1300
WINDOW_HEIGHT = 820

DEV_MODE = not getattr(sys, 'frozen', False)  # False when compiled to EXE

GITHUB_REPO = "juah3h32/FARMACIA"
GITHUB_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
