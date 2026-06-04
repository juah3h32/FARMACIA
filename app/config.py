from pathlib import Path
import os
import sys

APP_NAME = "Farmacia Eben-Ezer"
VERSION = "1.2.37"
PHARMACY_NAME = "FARMACIA EBEN-EZER"
PHARMACY_ADDRESS = "Dirección de la farmacia"
PHARMACY_PHONE = "Tel: 000-000-0000"
PHARMACY_RFC = "RFC: XXXX000000XX0"

BASE_DIR = Path(__file__).parent.parent

# Vercel sets VERCEL=1 in the environment
_ON_VERCEL = bool(os.getenv("VERCEL"))

# -- DATA_DIR -----------------------------------------------------------------
# Vercel:  /tmp (único dir escribible en lambdas — ephemeral, Turso es la fuente real)
# EXE:     %APPDATA%\FarmaciaEbenEzer\
# Dev:     /data/ junto al proyecto
if _ON_VERCEL:
    DATA_DIR = Path("/tmp/FarmaciaEbenEzer")
elif getattr(sys, 'frozen', False):
    DATA_DIR = Path(os.getenv('APPDATA', Path.home())) / "FarmaciaEbenEzer"
else:
    DATA_DIR = BASE_DIR / "data"

DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "farmacia.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

# -- Icon path ----------------------------------------------------------------
if getattr(sys, 'frozen', False):
    ICON_PATH = Path(sys._MEIPASS) / "assets" / "icon.ico"
else:
    ICON_PATH = BASE_DIR / "assets" / "icon.ico"

# -- Secret key ---------------------------------------------------------------
# En Vercel: leer de variable de entorno SECRET_KEY (configurar en Vercel dashboard)
# En EXE/dev: generar una vez y guardar en archivo local
if _ON_VERCEL:
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    if not SECRET_KEY:
        import secrets as _secrets
        SECRET_KEY = _secrets.token_hex(32)  # ephemeral — sesiones no sobreviven cold starts
else:
    _key_file = DATA_DIR / "secret.key"
    if _key_file.exists():
        SECRET_KEY = _key_file.read_text().strip()
    else:
        import secrets as _secrets
        SECRET_KEY = _secrets.token_hex(32)
        _key_file.write_text(SECRET_KEY)

# -- Turso (LibSQL) cloud DB --------------------------------------------------
# Prioridad: variables de entorno (Vercel dashboard) > valores hardcoded (fallback local)
TURSO_DATABASE_URL = os.getenv(
    "TURSO_DATABASE_URL",
    "libsql://farmacia-juanpa.aws-us-east-1.turso.io",
)
TURSO_AUTH_TOKEN = os.getenv(
    "TURSO_AUTH_TOKEN",
    (
        "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9"
        ".eyJhIjoicnciLCJpYXQiOjE3NzkxNTUwOTQsImlkIjoiMDE5ZTNkZTctZjQwMS03NmViLWFkYjgtZTRkMzAxZGExMTdjIiwicmlkIjoiNDVkNDAzNjItNzg4Ni00MDViLWE0Y2QtNDUxMjY1YTgxMzQ0In0"
        ".B3nY0-9gzbXkqNlj8MlzBjw44JP9OpVrG9QGrdx_tkB19QF8l7f5IgYoW3mLjOqUq4sTOVNQu78GEJMaVA0sDg"
    ),
)

# Vercel: Turso es la BD primaria (no hay disco persistente)
# EXE local: SQLite local + sync a Turso en background
USE_TURSO  = _ON_VERCEL
TURSO_SYNC = not _ON_VERCEL  # solo sincroniza local->Turso desde el EXE

API_HOST = "127.0.0.1"
API_PORT = 8000
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 8

TAX_RATE = 0.16
CURRENCY_SYMBOL = "$"
LOW_STOCK_THRESHOLD = 10
EXPIRY_ALERT_DAYS = 30

SIDEBAR_WIDTH = 230
WINDOW_WIDTH = 1300
WINDOW_HEIGHT = 820

# DEV_MODE: False en EXE compilado y en Vercel (no exponer /docs en producción)
DEV_MODE = not getattr(sys, 'frozen', False) and not _ON_VERCEL

GITHUB_REPO = "juah3h32/FARMACIA"
GITHUB_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
GITHUB_TOKEN = ""
