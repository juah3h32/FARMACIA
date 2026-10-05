"""
Mercado Pago Point (Point Smart / Point Smart 2) — integración vía **Orders API**.

Por qué Orders API y no la vieja "Point Integration API" (/point/integration-api/...):
Mercado Pago la marcó como reemplazada ("we're now offering a new API for
integrations with Mercado Pago Point, which will replace the current one") y
todo lo nuevo (incluido Point Smart 2 en México) se documenta solo con Orders:
  https://www.mercadopago.com.mx/developers/es/docs/mp-point/payment-processing
  https://www.mercadopago.com.mx/developers/en/docs/mp-point/migrate-payment-intent-to-orders
  https://www.mercadopago.com.mx/developers/es/docs/mp-point/resources/status-order-transaction

Endpoints:
  GET   /terminals/v1/list                 listar terminales de la cuenta
  PATCH /terminals/v1/setup                cambiar operating_mode a PDV
  POST  /v1/orders                         crear orden type=point (X-Idempotency-Key)
  GET   /v1/orders/{id}                    consultar (polling — app de escritorio sin URL pública)
  POST  /v1/orders/{id}/cancel             cancelar (solo mientras status=created)

Estados de la orden: created → at_terminal → processed | failed | canceled |
expired | action_required (además refunded).
"""
import requests
import uuid
from typing import Optional

MP_BASE = "https://api.mercadopago.com"

# Estados finales de una orden Point (Orders API)
FINAL_STATES = {"processed", "failed", "canceled", "expired", "refunded", "action_required"}

_DETAIL_ES = {
    "rejected_by_issuer":          "Rechazada por el banco emisor",
    "insufficient_amount":         "Fondos insuficientes",
    "card_disabled":               "Tarjeta desactivada",
    "high_risk":                   "Rechazada por seguridad (alto riesgo)",
    "bad_filled_card_data":        "Datos de tarjeta incorrectos",
    "required_call_for_authorize": "El banco pide llamar para autorizar",
    "max_attempts_exceeded":       "Se excedió el número de intentos",
    "amount_limit_exceeded":       "Excede el límite de monto",
    "processing_error":            "Error de procesamiento",
    "invalid_installments":        "Meses/cuotas inválidos",
    "in_review":                   "Pago en revisión",
    "canceled_on_terminal":        "Cancelado en la terminal",
    "canceled_by_api":             "Cancelado desde el POS",
    "check_on_terminal":           "Revisa el resultado en la terminal",
    "waiting_payment":             "Esperando pago",
    "expired":                     "La orden expiró sin pago",
}


class MercadoPagoError(Exception):
    def __init__(self, message: str, status_code: int = 502, code: str = ""):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


def detalle_es(detail: str) -> str:
    return _DETAIL_ES.get(detail or "", detail or "")


def _friendly_http_error(r: requests.Response, accion: str) -> MercadoPagoError:
    try:
        data = r.json()
    except Exception:
        data = {}
    errs = data.get("errors") or []
    code = ""
    msg = ""
    if errs and isinstance(errs, list) and isinstance(errs[0], dict):
        code = str(errs[0].get("code", ""))
        msg = str(errs[0].get("message", "") or errs[0].get("details", ""))
    code = code or str(data.get("error", "") or "")
    msg = msg or str(data.get("message", "") or "")
    low = (code + " " + msg).lower()
    if r.status_code == 401:
        return MercadoPagoError("Access Token de Mercado Pago inválido o vencido.", 401, code)
    if r.status_code == 403:
        return MercadoPagoError(
            "El Access Token no tiene permiso para Point. Usa el token de PRODUCCIÓN de tu "
            "aplicación en developers.mercadopago.com (Tus integraciones).", 403, code)
    if "terminal" in low and ("not found" in low or "linked" in low or "invalid" in low):
        return MercadoPagoError(
            "La terminal no está vinculada a esta cuenta o el ID de terminal es incorrecto.", 400, code)
    if "pdv" in low or "operating_mode" in low or "standalone" in low:
        return MercadoPagoError(
            "La terminal no está en modo PDV. Actívalo en Configuración > Mercado Pago y reinicia la terminal.",
            400, code)
    if "queue" in low or "already" in low or "busy" in low:
        return MercadoPagoError(
            "La terminal ya tiene un cobro pendiente. Cancélalo en la terminal e intenta de nuevo.", 409, code)
    if r.status_code == 409:
        return MercadoPagoError(f"Conflicto al {accion}: {msg or code}", 409, code)
    if r.status_code >= 500:
        return MercadoPagoError("Mercado Pago no responde en este momento. Intenta de nuevo.", 502, code)
    return MercadoPagoError(f"Error al {accion}: {msg or code or r.status_code}", 400 if r.status_code < 500 else 502, code)


class MercadoPagoPointService:
    def __init__(self):
        self.access_token: str = ""
        self.device_id: str = ""
        self.session = requests  # se puede reemplazar en tests
        self._loaded = False

    def configure(self, access_token: str, device_id: str):
        self.access_token = (access_token or "").strip()
        self.device_id = (device_id or "").strip()
        self._loaded = True

    def ensure_loaded(self) -> None:
        """Carga token/terminal si nadie llamó configure() (p. ej. servidor
        levantado sin main.py, o el token se guardó en otra PC y llegó por
        la tabla `configuracion` sincronizada con Turso)."""
        if self.access_token and self.device_id:
            return
        try:
            from app.services.mp_config import cargar_config
            tok, dev = cargar_config()
            if not self.access_token:
                self.access_token = tok
            if not self.device_id:
                self.device_id = dev
        except Exception:
            pass

    @property
    def enabled(self) -> bool:
        self.ensure_loaded()
        return bool(self.access_token and self.device_id)

    def _headers(self, token: Optional[str] = None, idem: Optional[str] = None) -> dict:
        h = {
            "Authorization": f"Bearer {token or self.access_token}",
            "Content-Type": "application/json",
        }
        if idem:
            h["X-Idempotency-Key"] = idem
        return h

    def _req(self, method: str, path: str, accion: str, token: Optional[str] = None,
             idem: Optional[str] = None, json: Optional[dict] = None, params: Optional[dict] = None,
             timeout: float = 12) -> dict:
        try:
            r = self.session.request(method, f"{MP_BASE}{path}", headers=self._headers(token, idem),
                                     json=json, params=params, timeout=timeout)
        except requests.exceptions.Timeout:
            raise MercadoPagoError("Mercado Pago tardó demasiado en responder (sin internet o red lenta).", 504)
        except requests.exceptions.RequestException:
            raise MercadoPagoError("Sin conexión a internet: no se pudo contactar a Mercado Pago.", 503)
        if r.status_code >= 400:
            raise _friendly_http_error(r, accion)
        try:
            return r.json() if r.content else {}
        except Exception:
            return {}

    # ── Terminales ──────────────────────────────────────────────────────────
    def list_terminals(self, token: Optional[str] = None) -> list:
        data = self._req("GET", "/terminals/v1/list", "listar terminales", token=token,
                         params={"limit": 50, "offset": 0})
        return (data.get("data") or {}).get("terminals", []) or []

    def set_pdv_mode(self, device_id: Optional[str] = None, token: Optional[str] = None) -> dict:
        did = device_id or self.device_id
        data = self._req("PATCH", "/terminals/v1/setup", "activar modo PDV", token=token,
                         json={"terminals": [{"id": did, "operating_mode": "PDV"}]})
        return data

    # ── Órdenes ─────────────────────────────────────────────────────────────
    def create_order(self, amount: float, external_reference: str, idempotency_key: Optional[str] = None,
                     description: str = "Venta farmacia", expiration: str = "PT5M") -> dict:
        """amount en pesos MXN (string con 2 decimales, como exige la API)."""
        self.ensure_loaded()
        if not self.device_id:
            raise MercadoPagoError("No hay terminal seleccionada.", 400)
        body = {
            "type": "point",
            "external_reference": external_reference[:64],
            "expiration_time": expiration,
            "description": description[:150],
            "transactions": {"payments": [{"amount": f"{round(float(amount), 2):.2f}"}]},
            "config": {"point": {"terminal_id": self.device_id, "print_on_terminal": "no_ticket"}},
        }
        return self._req("POST", "/v1/orders", "enviar el cobro a la terminal",
                         idem=idempotency_key or str(uuid.uuid4()), json=body, timeout=15)

    def get_order(self, order_id: str) -> dict:
        self.ensure_loaded()
        return self._req("GET", f"/v1/orders/{order_id}", "consultar el cobro")

    def cancel_order(self, order_id: str) -> dict:
        self.ensure_loaded()
        return self._req("POST", f"/v1/orders/{order_id}/cancel", "cancelar el cobro",
                         idem=f"cancel-{order_id}")

    @staticmethod
    def resumen(order: dict) -> dict:
        """Normaliza la orden a lo que necesita el POS."""
        pays = ((order.get("transactions") or {}).get("payments") or [])
        p = pays[0] if pays else {}
        status = (order.get("status") or "").lower()
        detail = (p.get("status_detail") or order.get("status_detail") or "")
        pm = p.get("payment_method") or {}
        return {
            "order_id":      order.get("id"),
            "status":        status,
            "status_detail": detail,
            "detalle":       detalle_es(detail),
            "payment_id":    p.get("id"),
            "amount":        p.get("amount"),
            "card":          pm.get("id") or "",
            "card_type":     pm.get("type") or "",
            "last_four":     (pm.get("last_four_digits") or ""),
            "reference_id":  p.get("reference_id") or "",
        }


mp_point = MercadoPagoPointService()
