from pathlib import Path
import os
import sys

APP_NAME = "Farmacia Eben-Ezer"
VERSION = "2.3.72"
PHARMACY_NAME = "FARMACIA EBEN-EZER"
PHARMACY_ADDRESS = "ESFUERZO #47 COL. 13 DE ABRIL"
PHARMACY_PHONE = "Tel: 443-423-1168"
PHARMACY_RFC = "BESA9907157AA"
# Datos fiscales para CFDI (persona física RESICO) — el nombre del emisor en el CFDI
# debe ser el nombre registrado ante el SAT, no el nombre comercial de la farmacia.
PHARMACY_RAZON_SOCIAL_FISCAL = "ADRIANA LIZETH BEDOLLA SALINAS"
PHARMACY_CP_FISCAL = "58314"
PHARMACY_REGIMEN_FISCAL = "626"  # Régimen Simplificado de Confianza (RESICO)

BASE_DIR = Path(__file__).parent.parent

# Vercel sets VERCEL=1 in the environment
_ON_VERCEL = bool(os.getenv("VERCEL"))

# -- DATA_DIR -----------------------------------------------------------------
# Vercel:  /tmp (único dir escribible en lambdas — ephemeral, Turso es la fuente real)
# EXE:     %APPDATA%\FarmaciaEbenEzer\
# Dev:     /data/ junto al proyecto
if os.getenv('FARMACIA_DATA_DIR'):
    DATA_DIR = Path(os.getenv('FARMACIA_DATA_DIR'))
elif _ON_VERCEL:
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

# -- Carga de claves desde archivos locales -----------------------------------
# Prioridad: variable de entorno > archivo en DATA_DIR > vacío
def _load_key(env_name: str, filename: str) -> str:
    val = os.getenv(env_name, "")
    if not val:
        kf = DATA_DIR / filename
        if kf.exists():
            try:
                val = kf.read_text(encoding="utf-8").strip()
            except Exception:
                pass
    return val

# -- Turso (LibSQL) cloud DB --------------------------------------------------
TURSO_DATABASE_URL = os.getenv(
    "TURSO_DATABASE_URL",
    "libsql://farmacia-juanpa.aws-us-east-1.turso.io",
)
TURSO_AUTH_TOKEN = _load_key("TURSO_AUTH_TOKEN", "turso.key") or (
    "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9"
    ".eyJhIjoicnciLCJpYXQiOjE3NzkxNTUwOTQsImlkIjoiMDE5ZTNkZTctZjQwMS03NmViLWFkYjgtZTRkMzAxZGExMTdjIiwicmlkIjoiNDVkNDAzNjItNzg4Ni00MDViLWE0Y2QtNDUxMjY1YTgxMzQ0In0"
    ".B3nY0-9gzbXkqNlj8MlzBjw44JP9OpVrG9QGrdx_tkB19QF8l7f5IgYoW3mLjOqUq4sTOVNQu78GEJMaVA0sDg"
)

# -- Modo de sincronización (elegido en el asistente de primer arranque) ------
# "turso"   = SQLite local + sincroniza con la nube (multi-PC)
# "local"   = solo SQLite local, nunca intenta red — un solo equipo para siempre
# "offline" = igual que local, pero pensado como estado temporal (sin internet
#             ahora mismo) — se puede volver a activar Turso después
import json as _json

SETUP_FILE = DATA_DIR / "setup.json"


def _load_setup() -> dict:
    if SETUP_FILE.exists():
        try:
            return _json.loads(SETUP_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def reload_setup() -> None:
    """Re-lee setup.json y actualiza SYNC_MODE/USE_TURSO/TURSO_SYNC en caliente —
    se llama justo después de que el asistente de primer arranque guarda la elección."""
    global SYNC_MODE, USE_TURSO, TURSO_SYNC, NEEDS_FIRST_RUN_SETUP
    _setup = _load_setup()

    # Instalación existente (viene de una versión anterior a este asistente, o
    # simplemente nunca guardó setup.json) — ya tiene farmacia.db con datos reales.
    # Eso es una ACTUALIZACIÓN, no una instalación nueva: no mostrar el asistente,
    # solo asumir "turso" (el comportamiento de siempre antes de que existiera este
    # asistente) y persistirlo en silencio para no volver a preguntar.
    if "sync_mode" not in _setup and DB_PATH.exists():
        _setup["sync_mode"] = "turso"
        try:
            SETUP_FILE.write_text(_json.dumps(_setup), encoding="utf-8")
        except Exception:
            pass

    SYNC_MODE = _setup.get("sync_mode", "turso")
    NEEDS_FIRST_RUN_SETUP = (not _ON_VERCEL) and "sync_mode" not in _setup
    USE_TURSO  = _ON_VERCEL
    TURSO_SYNC = (not _ON_VERCEL) and SYNC_MODE == "turso"


# Vercel: Turso es la BD primaria (no hay disco persistente) — siempre, sin asistente.
# EXE local: el asistente de primer arranque decide (turso/local/offline), guardado en setup.json.
SYNC_MODE = "turso"
NEEDS_FIRST_RUN_SETUP = False
USE_TURSO  = _ON_VERCEL
TURSO_SYNC = not _ON_VERCEL
reload_setup()

API_HOST = "127.0.0.1"
API_PORT = 8000
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 12

TAX_RATE = 0.16
CURRENCY_SYMBOL = "$"
LOW_STOCK_THRESHOLD = 10
EXPIRY_ALERT_DAYS = 30

SIDEBAR_WIDTH = 230
WINDOW_WIDTH = 1300
WINDOW_HEIGHT = 820

# DEV_MODE: False en EXE compilado y en Vercel (no exponer /docs en producción)
DEV_MODE = not getattr(sys, 'frozen', False) and not _ON_VERCEL

VERCEL_URL  = os.getenv("VERCEL_URL", "https://farmacia-ebenezer.com")

GITHUB_REPO = "juah3h32/FARMACIA"
GITHUB_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
GITHUB_TOKEN = ""

CLOUDINARY_CLOUD_NAME = _load_key("CLOUDINARY_CLOUD_NAME", "cloudinary_cloud.key") or "dcutrbbyw"
CLOUDINARY_API_KEY    = _load_key("CLOUDINARY_API_KEY",    "cloudinary_api.key")    or "717952968559447"
CLOUDINARY_API_SECRET = _load_key("CLOUDINARY_API_SECRET", "cloudinary_secret.key") or "gufXKh1BIUTfsdwKNzz95or4SI4"

# -- Mercado Pago Point (terminal de pago ME30S) ------------------------------
MP_ACCESS_TOKEN = _load_key("MP_ACCESS_TOKEN", "mp_access_token.key") or (
    "APP_USR-6410994072397818-062114-f98cacf3ef24f92ce1941c5545cc7e03-3486812391"
)
MP_DEVICE_ID    = _load_key("MP_DEVICE_ID",    "mp_device_id.key")


def _load_openai_key() -> str:
    key = _load_key("OPENAI_API_KEY", "openai.key")
    if not key:
        key = (
            "sk-proj-Yoq_JrjHgsJ9RuPMb2BrJHP83mVweP9-ZBR-ZcKx8DoYZEUoupZc1lcRE6LHP4Ch1aZ8NXfGA"
            "CT3BlbkFJg8p-I6iOthjveaONV4Luj8UDfuH4Do-gu7YQqWJI-2BdHU_6rtUd4F2xeE28LgumO63vq4XDcA"
        )
    return key


OPENAI_API_KEY = _load_openai_key()
