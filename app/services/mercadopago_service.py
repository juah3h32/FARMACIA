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
# "action_required" NO es final: la orden espera una confirmación en la terminal
# (status_detail waiting_payment / check_on_terminal) → se sigue consultando.
FINAL_STATES = {"processed", "failed", "canceled", "expired", "refunded"}

# Errores de Mercado Pago con causa conocida (códigos documentados o vistos en
# casos reales). Con estos NO se intenta la API anterior: el problema no es
# "API no habilitada" sino la configuración de la cuenta/terminal.
_CODIGOS_ES = {
    # 403 en /users/me o /terminals con bloqueo de políticas: credenciales de
    # producción sin activar (Industria / Sitio web / términos), verificación de
    # identidad pendiente o token equivocado.
    "PA_UNAUTHORIZED_RESULT_FROM_POLICIES":
        "Mercado Pago bloqueó este Access Token por políticas de la cuenta: activa las credenciales de "
        "producción (developers > Tus integraciones > tu app > Credenciales de producción: llena Industria "
        "y Sitio web y acepta los términos), revisa que la verificación de identidad de la cuenta esté "
        "completa o contacta a soporte de Mercado Pago.",
    "store_pos_not_found":
        "La terminal no está asignada a una sucursal y caja. En mercadopago.com.mx > Tu negocio > "
        "Sucursales y cajas asígnala a una caja y vuelve a intentar.",
    "terminal_not_allowed_action":
        "Este modelo de terminal no permite esa acción por API.",
    "forbidden_checking_terminal_owner":
        "La terminal pertenece a OTRA cuenta de Mercado Pago distinta a la del Access Token.",
    "already_queued_order_for_terminal":
        "La terminal ya tiene un cobro pendiente. Termínalo o cancélalo en la terminal e intenta de nuevo.",
    "cannot_cancel_order":
        "El cobro ya está en la pantalla de la terminal: cancélalo desde la terminal.",
}

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
    def __init__(self, message: str, status_code: int = 502, code: str = "", raw: str = ""):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.raw = raw  # texto original de Mercado Pago (para diagnóstico)

    @property
    def http_status(self) -> int:
        """Código HTTP para responderle al frontend. Un 401 de Mercado Pago NO se
        reenvía como 401: api() del frontend lo toma como sesión vencida y
        cierra la sesión del cajero/admin a mitad de la venta."""
        return 400 if self.status_code == 401 else self.status_code


def limpiar_token(token: Optional[str]) -> str:
    """Limpia lo que suele colarse al copiar/pegar el Access Token: espacios,
    saltos de línea, comillas, un "Bearer " delante, o la máscara "••••abcd"
    que muestra la pantalla cuando el usuario pega el token nuevo SIN borrarla
    (quedaría "••••abcdAPP_USR-..." y se ignoraba el token nuevo)."""
    t = "".join((token or "").split()).strip("\"'")
    if t.lower().startswith("bearer"):
        t = t[6:]
    for pref in ("APP_USR-", "TEST-"):
        i = t.find(pref)
        if i > 0:
            t = t[i:]
            break
    return t


def referencia_externa(ref: Optional[str]) -> str:
    """external_reference de MP: solo [A-Za-z0-9_-], máximo 64, sin datos personales."""
    import re
    return re.sub(r"[^A-Za-z0-9_-]", "", ref or "")[:64] or uuid.uuid4().hex


def device_valido(device_id: Optional[str]) -> bool:
    # IDs reales: "NEWLAND_N950__N950NCB801293324", "GERTEC_MP35P__..." etc.
    d = (device_id or "").strip()
    return bool(d and len(d) > 8 and " " not in d and not d.isdigit())


def detalle_es(detail: str) -> str:
    return _DETAIL_ES.get(detail or "", detail or "")


def _friendly_http_error(r: requests.Response, accion: str) -> MercadoPagoError:
    try:
        data = r.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    errs = data.get("errors") or []
    code = ""
    msg = ""
    if errs and isinstance(errs, list) and isinstance(errs[0], dict):
        code = str(errs[0].get("code", ""))
        msg = str(errs[0].get("message", "") or errs[0].get("details", ""))
    # El bloqueo por políticas llega como {"code": "PA_UNAUTHORIZED_RESULT_FROM_POLICIES",
    # "blocked_by": "PolicyAgent", ...}: también se lee la llave "code"
    code = code or str(data.get("error", "") or data.get("code", "") or "")
    msg = msg or str(data.get("message", "") or "")
    low = (code + " " + msg).lower()
    # Texto crudo de MP: se agrega a los mensajes para que el dueño vea
    # exactamente qué contestó Mercado Pago (antes solo se veía la traducción).
    raw = f"HTTP {r.status_code}" + (f" {code}" if code else "") + (f": {msg}" if msg and msg != code else "")
    mp_dice = f" [Mercado Pago: {raw}]"
    if r.status_code == 401:
        return MercadoPagoError("Access Token de Mercado Pago inválido o vencido." + mp_dice, 401, code, raw)
    for k, txt in _CODIGOS_ES.items():
        if k.lower() in low:
            st = 409 if r.status_code == 409 else (403 if r.status_code == 403 else 400)
            return MercadoPagoError(txt + mp_dice, st, k, raw)
    if r.status_code == 412:
        return MercadoPagoError(
            "Ya hay otra terminal en modo PDV en esa caja de Mercado Pago. Cada caja admite una sola "
            "terminal en PDV: asigna esta terminal a otra caja." + mp_dice, 412, code, raw)
    if r.status_code == 403:
        # Ojo: en el panel nuevo de MP el token de PRUEBA también empieza con
        # APP_USR-, así que el prefijo no prueba que sea de producción.
        return MercadoPagoError(
            "Mercado Pago no permitió " + accion + " con este Access Token. Revisa que sea el token de "
            "PRODUCCIÓN (Credenciales de producción, ya activadas) de la misma cuenta donde está "
            "vinculada la terminal." + mp_dice, 403, code, raw)
    if "terminal" in low and ("not found" in low or "linked" in low or "invalid" in low):
        return MercadoPagoError(
            "La terminal no está vinculada a esta cuenta o el ID de terminal es incorrecto." + mp_dice,
            400, code, raw)
    if "pdv" in low or "operating_mode" in low or "standalone" in low:
        return MercadoPagoError(
            "La terminal no está en modo PDV. Actívalo en Configuración > Mercado Pago y reinicia la terminal."
            + mp_dice, 400, code, raw)
    if "queue" in low or "already" in low or "busy" in low:
        return MercadoPagoError(
            "La terminal ya tiene un cobro pendiente. Cancélalo en la terminal e intenta de nuevo." + mp_dice,
            409, code, raw)
    if r.status_code == 409:
        return MercadoPagoError(f"Conflicto al {accion}: {msg or code}", 409, code, raw)
    if r.status_code >= 500:
        return MercadoPagoError("Mercado Pago no responde en este momento. Intenta de nuevo." + mp_dice,
                                502, code, raw)
    # 404 se conserva (decide si se prueba la API anterior); lo demás es 400
    return MercadoPagoError(f"Error al {accion}: {msg or code or r.status_code}",
                            404 if r.status_code == 404 else 400, code, raw)


def _combinar(e_nueva: MercadoPagoError, e_ant: MercadoPagoError) -> MercadoPagoError:
    """Fallaron la API nueva y la anterior: se reporta el error de la nueva con el
    texto crudo de las dos (antes se perdía lo que dijo la API anterior)."""
    raw = f"API nueva: {e_nueva.raw or e_nueva.message} | API anterior: {e_ant.raw or e_ant.message}"
    msg = e_nueva.message.split(" [Mercado Pago:")[0] + f" [Mercado Pago — {raw}]"
    return MercadoPagoError(msg, e_nueva.status_code, e_nueva.code, raw)


def _usar_api_anterior(e: MercadoPagoError) -> bool:
    """¿Reintentar con /point/integration-api? Sí cuando la API nueva responde
    403/404 (cuenta o aplicación sin Orders/terminals habilitado) o dice que no
    conoce la terminal (terminal que solo aparece en la API anterior)."""
    if e.code in _CODIGOS_ES or e.status_code == 412:
        return False  # causa conocida: la API anterior no lo arreglaría
    if e.status_code in (403, 404):
        return True
    low = f"{e.code} {e.raw}".lower()
    return e.status_code == 400 and "terminal" in low and ("not found" in low or "invalid" in low)


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

    def recargar(self) -> None:
        """Vuelve a leer token/terminal guardados. Si el dueño cambió el token en
        otra PC (llega por la tabla `configuracion`), esta PC lo toma sin reiniciar."""
        try:
            from app.services.mp_config import cargar_config
            tok, dev = cargar_config()
            if tok:
                self.access_token = tok
            if dev:
                self.device_id = dev
        except Exception:
            pass

    @property
    def enabled(self) -> bool:
        # Mismo criterio que /config/mp-status (antes uno validaba el formato del
        # ID y el otro no: el badge y el POS podían contradecirse)
        self.ensure_loaded()
        return bool(self.access_token and device_valido(self.device_id))

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

    # ── Cuenta ──────────────────────────────────────────────────────────────
    def verificar_token(self, token: Optional[str] = None) -> dict:
        """Confirma que el token sirve y de qué cuenta es (antes de culpar a Point).
        Un token de prueba (TEST-...) o de otro país no sirve con la terminal."""
        t = limpiar_token(token) or (self.access_token or "").strip()
        if t.upper().startswith("TEST-"):
            raise MercadoPagoError(
                "Ese es un token de PRUEBA (TEST-...). Usa el Access Token de Credenciales de producción.", 400)
        try:
            me = self._req("GET", "/users/me", "verificar el Access Token", token=t)
        except MercadoPagoError as e:
            if e.status_code in (401, 403):
                # 403 en /users/me = problema de la cuenta/token (credenciales de
                # producción sin activar, cuenta bloqueada): no tiene caso seguir
                raise
            return {}  # sin red / MP caído: no se pudo confirmar, no bloquea la detección
        if me.get("site_id") and me.get("site_id") != "MLM":
            raise MercadoPagoError(
                f"El token es de una cuenta de otro país ({me.get('site_id')}); se necesita una cuenta de México.", 400)
        return {"user_id": me.get("id"), "nickname": me.get("nickname"), "site_id": me.get("site_id")}

    # ── Terminales ──────────────────────────────────────────────────────────
    # Si la cuenta no tiene habilitada la API nueva (/terminals, /v1/orders) y
    # Mercado Pago responde 403/404, se usa la API anterior de Point
    # (/point/integration-api), que muchas cuentas de México siguen teniendo.
    def _list_legacy(self, token: Optional[str] = None) -> list:
        data = self._req("GET", "/point/integration-api/devices", "listar terminales", token=token)
        return [
            {"id": d.get("id"), "operating_mode": d.get("operating_mode", ""),
             "store_id": d.get("store_id"), "pos_id": d.get("pos_id"),
             "external_pos_id": d.get("external_pos_id"), "api": "anterior"}
            for d in (data.get("devices") or [])
        ]

    def list_terminals(self, token: Optional[str] = None) -> list:
        try:
            data = self._req("GET", "/terminals/v1/list", "listar terminales", token=token,
                             params={"limit": 50, "offset": 0})
            terms = (data.get("data") or {}).get("terminals", []) or []
        except MercadoPagoError as e:
            if not _usar_api_anterior(e):
                raise
            try:
                return self._list_legacy(token)
            except MercadoPagoError as e2:
                raise _combinar(e, e2)
        if terms:
            return [dict(t, api="nueva") for t in terms]
        # La API nueva respondió bien pero sin terminales: hay cuentas cuya
        # terminal solo aparece en la API anterior → se consulta también.
        try:
            return self._list_legacy(token)
        except MercadoPagoError:
            return []

    def set_pdv_mode(self, device_id: Optional[str] = None, token: Optional[str] = None) -> dict:
        did = device_id or self.device_id
        try:
            return self._req("PATCH", "/terminals/v1/setup", "activar modo PDV", token=token,
                             json={"terminals": [{"id": did, "operating_mode": "PDV"}]})
        except MercadoPagoError as e:
            if not _usar_api_anterior(e):
                raise
            try:
                return self._req("PATCH", f"/point/integration-api/devices/{did}", "activar modo PDV",
                                 token=token, json={"operating_mode": "PDV"})
            except MercadoPagoError as e2:
                raise _combinar(e, e2)

    # ── Órdenes ─────────────────────────────────────────────────────────────
    def create_order(self, amount: float, external_reference: str, idempotency_key: Optional[str] = None,
                     description: str = "Venta farmacia", expiration: str = "PT5M") -> dict:
        """amount en pesos MXN (string con 2 decimales, como exige la API)."""
        self.ensure_loaded()
        if not self.device_id:
            raise MercadoPagoError("No hay terminal seleccionada.", 400)
        external_reference = referencia_externa(external_reference)
        body = {
            "type": "point",
            "external_reference": external_reference,
            "expiration_time": expiration,
            "description": description[:150],
            "transactions": {"payments": [{"amount": f"{round(float(amount), 2):.2f}"}]},
            "config": {"point": {"terminal_id": self.device_id, "print_on_terminal": "no_ticket"}},
        }
        idem = idempotency_key or str(uuid.uuid4())
        try:
            try:
                return self._req("POST", "/v1/orders", "enviar el cobro a la terminal",
                                 idem=idem, json=body, timeout=15)
            except MercadoPagoError as e0:
                # La llave ya se usó con OTRO cuerpo (p. ej. el cobro salió de
                # mp_pendientes.json): se reintenta una vez con llave nueva. Si hubiera
                # otro cobro vivo, MP responde already_queued_order_for_terminal.
                if "idempotency_key_already_used" not in f"{e0.code} {e0.raw}".lower():
                    raise
                idem = f"{idem[:40]}-{uuid.uuid4().hex[:12]}"
                return self._req("POST", "/v1/orders", "enviar el cobro a la terminal",
                                 idem=idem, json=body, timeout=15)
        except MercadoPagoError as e:
            if not _usar_api_anterior(e):
                raise
            # API anterior: payment intent en la terminal (monto en centavos)
            try:
                pi = self._req(
                    "POST", f"/point/integration-api/devices/{self.device_id}/payment-intents",
                    "enviar el cobro a la terminal", idem=idem, timeout=15,
                    json={"amount": int(round(float(amount) * 100)),
                          "additional_info": {"external_reference": external_reference[:64],
                                              "print_on_terminal": False}})
            except MercadoPagoError as e2:
                raise _combinar(e, e2)
            # La respuesta de creación no trae "state": recién creado = OPEN
            return self._intent_como_orden(dict(pi, state=pi.get("state") or "OPEN"))

    # Estados de la API anterior → estados de Orders que entiende el POS
    _PI_ESTADOS = {"OPEN": "created", "ON_TERMINAL": "at_terminal", "PROCESSING": "at_terminal",
                   "CANCELED": "canceled", "ABANDONED": "expired", "ERROR": "failed"}

    def _intent_como_orden(self, pi: dict) -> dict:
        """Traduce un payment intent a la forma de una orden (para resumen())."""
        estado = (pi.get("state") or "").upper()
        pago = pi.get("payment") or {}
        pid = pago.get("id")
        status, detail, pm, monto = self._PI_ESTADOS.get(estado, "at_terminal"), "", {}, None
        if estado in ("FINISHED", "PROCESSED"):
            if pid:
                try:
                    pay = self._req("GET", f"/v1/payments/{pid}", "consultar el pago")
                except MercadoPagoError:
                    pay = {}
                st = (pay.get("status") or "").lower()
                status = "processed" if st == "approved" else ("at_terminal" if st in ("", "in_process", "pending") else "failed")
                detail = pay.get("status_detail") or ""
                monto = pay.get("transaction_amount")
                pm = {"id": pay.get("payment_method_id") or "", "type": pay.get("payment_type_id") or "",
                      "last_four_digits": ((pay.get("card") or {}).get("last_four_digits") or "")}
            else:
                status, detail = "failed", "processing_error"
        elif estado == "CANCELED":
            detail = "canceled_on_terminal"
        return {"id": f"PI:{pi.get('id')}", "status": status, "status_detail": detail,
                "transactions": {"payments": [{"id": pid, "amount": monto, "status_detail": detail,
                                               "payment_method": pm}]}}

    def imprimir_en_terminal(self, contenido: str, referencia: str) -> dict:
        """Imprime texto propio en la impresora de la terminal (Point Smart 1 y 2).
        Mercado Pago responde 409 already_queued_order_for_terminal si la
        terminal todavía tiene un cobro en curso."""
        self.ensure_loaded()
        if not self.device_id:
            raise MercadoPagoError("No hay terminal seleccionada en esta caja.", 400)
        ref = referencia_externa(referencia)
        return self._req("POST", "/terminals/v1/actions", "imprimir en la terminal",
                         idem=f"print-{ref}-{uuid.uuid4().hex[:8]}", timeout=15,
                         json={"type": "print", "external_reference": ref,
                               "config": {"point": {"terminal_id": self.device_id, "subtype": "custom"}},
                               "content": contenido})

    def get_order(self, order_id: str) -> dict:
        self.ensure_loaded()
        if str(order_id).startswith("PI:"):
            pi = self._req("GET", f"/point/integration-api/payment-intents/{order_id[3:]}", "consultar el cobro")
            return self._intent_como_orden(pi)
        return self._req("GET", f"/v1/orders/{order_id}", "consultar el cobro")

    def cancel_order(self, order_id: str, device_id: Optional[str] = None) -> dict:
        self.ensure_loaded()
        if str(order_id).startswith("PI:"):
            # La terminal con la que SE CREÓ el cobro (la configuración pudo cambiar después)
            did = device_id or self.device_id
            self._req("DELETE", f"/point/integration-api/devices/{did}/payment-intents/{order_id[3:]}",
                      "cancelar el cobro")
            return self.get_order(order_id)
        return self._req("POST", f"/v1/orders/{order_id}/cancel", "cancelar el cobro",
                         idem=f"cancel-{order_id}")

    # ── Diagnóstico ─────────────────────────────────────────────────────────
    def _crudo(self, method: str, path: str, token: str, params: Optional[dict] = None):
        """Llamada SIN traducir errores: regresa (http_status, json, texto_mp).
        http_status = 0 si no hubo conexión."""
        try:
            r = self.session.request(method, f"{MP_BASE}{path}", headers=self._headers(token),
                                     params=params, json=None, timeout=12)
        except requests.exceptions.RequestException as ex:
            return 0, {}, f"Sin conexión con Mercado Pago ({type(ex).__name__})"
        try:
            data = r.json() if r.content else {}
        except Exception:
            data = {}
        if r.status_code < 400:
            return r.status_code, data if isinstance(data, (dict, list)) else {}, ""
        return r.status_code, {}, _friendly_http_error(r, "consultar").raw

    def diagnostico(self, token: Optional[str] = None, device_id: Optional[str] = None) -> dict:
        """Revisa paso a paso token, cuenta, terminales (API nueva y anterior),
        sucursales/cajas y la terminal elegida. Nunca lanza: cada paso trae
        ok=True/False/None (None = aviso u omitido) y el texto crudo de MP."""
        self.ensure_loaded()
        t = limpiar_token(token) or self.access_token
        did = (device_id or "").strip() or self.device_id
        pasos = []

        def paso(nombre, ok, detalle, mp=""):
            pasos.append({"paso": nombre, "ok": ok, "detalle": detalle, "mp": mp})

        # 1) Formato del token
        if not t:
            paso("Formato del Access Token", False, "No hay Access Token capturado ni guardado.")
            return {"pasos": pasos, "conclusion": "Captura el Access Token de Credenciales de producción."}
        fin = t[-4:] if len(t) > 8 else ""
        if t.upper().startswith("TEST-"):
            paso("Formato del Access Token", False,
                 f"Es un token de PRUEBA (TEST-…{fin}). La terminal solo funciona con el de Credenciales de producción.")
        elif t.startswith("APP_USR-"):
            # En el panel nuevo el token de prueba TAMBIÉN empieza con APP_USR-:
            # el formato es correcto, pero no prueba que sea de producción.
            paso("Formato del Access Token", True,
                 f"Formato correcto (APP_USR-…{fin}). Confirma que lo copiaste de 'Credenciales de producción'.")
        else:
            paso("Formato del Access Token", None,
                 f"No empieza con APP_USR- (…{fin}). ¿Se copió completo? ¿No es la Public Key o el Client Secret?")

        # 2) Cuenta dueña del token
        st, me, raw = self._crudo("GET", "/users/me", t)
        user_id = None
        if st == 200 and isinstance(me, dict):
            user_id = me.get("id")
            site = me.get("site_id") or "?"
            paso("Cuenta del token (/users/me)", site == "MLM",
                 f"Cuenta {me.get('nickname') or '?'} (id {user_id}, país {site})"
                 + ("" if site == "MLM" else " — se necesita una cuenta de México (MLM)") + ".")
        else:
            paso("Cuenta del token (/users/me)", False,
                 "Token inválido o vencido." if st == 401 else
                 ("Cuenta/token bloqueado por Mercado Pago: activa las Credenciales de producción (Industria, "
                  "Sitio web y términos) y revisa que la verificación de identidad de la cuenta esté completa; "
                  "si sigue igual, contacta a soporte de Mercado Pago." if st == 403 else
                  "No se pudo consultar la cuenta."), raw)

        # 3) Terminales — API nueva (Orders)
        st, data, raw = self._crudo("GET", "/terminals/v1/list", t, {"limit": 50, "offset": 0})
        nuevas = []
        if st == 200 and isinstance(data, dict):
            nuevas = (data.get("data") or {}).get("terminals", []) or []
            paso("Terminales — API nueva (/terminals/v1/list)", bool(nuevas) or None,
                 (f"{len(nuevas)} terminal(es): " + ", ".join(
                     f"{x.get('id')} [{x.get('operating_mode') or '?'}]" for x in nuevas))
                 if nuevas else "La API respondió bien pero sin terminales vinculadas.")
        else:
            paso("Terminales — API nueva (/terminals/v1/list)", False,
                 "Sin permiso para la API nueva de Point." if st == 403 else "No se pudo listar.", raw)

        # 4) Terminales — API anterior (Point Integration API)
        st, data, raw = self._crudo("GET", "/point/integration-api/devices", t)
        viejas = []
        if st == 200 and isinstance(data, dict):
            viejas = data.get("devices") or []
            paso("Terminales — API anterior (/point/integration-api/devices)", bool(viejas) or None,
                 (f"{len(viejas)} terminal(es): " + ", ".join(
                     f"{x.get('id')} [{x.get('operating_mode') or '?'}]" for x in viejas))
                 if viejas else "La API respondió bien pero sin terminales vinculadas.")
        else:
            paso("Terminales — API anterior (/point/integration-api/devices)", False,
                 "Sin permiso para la API anterior de Point." if st == 403 else "No se pudo listar.", raw)
        # Basta con que UNA de las dos APIs funcione: la otra queda como aviso
        if nuevas or viejas:
            for p in pasos[-2:]:
                if p["ok"] is False:
                    p["ok"] = None
                    p["detalle"] += " (No bloquea: el POS usa la otra API.)"
        elif all(p["ok"] is None for p in pasos[-2:]):
            pasos[-1]["ok"] = False  # ambas respondieron bien pero ninguna tiene terminales

        # 5) Sucursales de la cuenta
        if user_id:
            st, data, raw = self._crudo("GET", f"/users/{user_id}/stores/search", t)
            if st == 200 and isinstance(data, dict):
                tiendas = data.get("results") or []
                paso("Sucursales (/users/{id}/stores/search)", bool(tiendas) or None,
                     (f"{len(tiendas)} sucursal(es): " + ", ".join(
                         f"{x.get('name') or '?'} (id {x.get('id')})" for x in tiendas[:10]))
                     if tiendas else "La cuenta no tiene sucursales: créala en Tu negocio > Sucursales y cajas.")
            else:
                paso("Sucursales (/users/{id}/stores/search)", False, "No se pudieron consultar.", raw)
        else:
            paso("Sucursales (/users/{id}/stores/search)", None, "Omitido: no se identificó la cuenta.")

        # 6) Cajas (POS) de la cuenta
        st, data, raw = self._crudo("GET", "/pos", t)
        if st == 200 and isinstance(data, dict):
            cajas = data.get("results") or []
            paso("Cajas (/pos)", bool(cajas) or None,
                 (f"{len(cajas)} caja(s): " + ", ".join(
                     f"{x.get('name') or '?'} (ext {x.get('external_id') or '-'})" for x in cajas[:10]))
                 if cajas else "La cuenta no tiene cajas: la terminal debe vincularse a una caja.")
        else:
            paso("Cajas (/pos)", False, "No se pudieron consultar.", raw)

        # 7) y 8) Terminal elegida en esta PC
        todas = [dict(x, api="nueva") for x in nuevas] + [dict(x, api="anterior") for x in viejas]
        sel = next((x for x in todas if x.get("id") == did), None) if did else None
        if not did:
            paso("Terminal elegida en esta PC", False, "No hay terminal elegida: usa Detectar y Guardar.")
        elif not todas:
            paso("Terminal elegida en esta PC", None,
                 f"{did}: no se puede verificar porque Mercado Pago no devolvió ninguna lista de terminales.")
        elif not sel:
            paso("Terminal elegida en esta PC", False,
                 f"{did} no aparece en las terminales de esta cuenta (¿otra cuenta o ID mal copiado?).")
        else:
            paso("Terminal elegida en esta PC", True, f"{did} encontrada (API {sel['api']}).")
        if sel and sel["api"] == "nueva":
            # Terminal listada sin pos_id = no está asignada a una caja
            paso("Terminal asignada a una caja (pos_id)", bool(sel.get("pos_id")),
                 f"Caja {sel.get('pos_id')} (sucursal {sel.get('store_id') or '?'})." if sel.get("pos_id") else
                 "La terminal no está asignada a ninguna caja: asígnala en Tu negocio > Sucursales y cajas.")
        if sel:
            modo = (sel.get("operating_mode") or "").upper()
            paso("Modo de operación (operating_mode)", modo == "PDV",
                 "PDV — lista para recibir cobros del POS." if modo == "PDV" else
                 f"Está en modo {modo or 'desconocido'}: usa 'Activar modo PDV' (o en la terminal: Más opciones "
                 "> Ajustes > Modo de vinculación > Punto de Venta) y REINICIA la terminal.")

        # Conclusión breve para el dueño
        fallo = next((p for p in pasos if p["ok"] is False), None)
        if not fallo:
            conclusion = "Todo en orden: la terminal debería recibir los cobros."
        else:
            conclusion = f"Primer problema: {fallo['paso']} — {fallo['detalle']}"
            if fallo.get("mp"):
                conclusion += f" (Mercado Pago: {fallo['mp']})"
        return {"pasos": pasos, "conclusion": conclusion}

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


def texto_ticket_terminal(data: dict, farmacia: str = "", sucursal: str = "") -> str:
    """Comprobante con productos para la impresora de la Point (POST
    /terminals/v1/actions, subtype=custom). Usa las etiquetas de Mercado Pago
    ({b},{w},{s},{br},{center}); el contenido debe medir entre 100 y 4096
    caracteres. Ref: https://www.mercadopago.com.mx/developers/es/docs/mp-point/configure-printings"""
    def limpio(t) -> str:
        # Las llaves son etiquetas de MP: nunca dejarlas en texto libre
        return str(t or "").replace("{", "(").replace("}", ")")
    lineas = ["{br}{center}{b}" + limpio(farmacia or "FARMACIA") + "{/b}{/center}"]
    if sucursal and sucursal.lower() != "matriz":
        lineas.append("{center}Sucursal " + limpio(sucursal) + "{/center}")
    lineas.append("{center}{s}Detalle de venta - Folio " + limpio(data.get("folio")) + "{/s}{/center}")
    if data.get("fecha"):
        lineas.append("{center}{s}" + limpio(data["fecha"]) + "{/s}{/center}")
    lineas.append("{br}--------------------------------")
    for it in data.get("items", []):
        lineas.append("{left}" + limpio(it.get("nombre"))[:32] + "{/left}")
        lineas.append("{left}  " + str(it.get("cantidad")) + " x $" + f"{float(it.get('precio_unitario') or 0):.2f}"
                      + "   $" + f"{float(it.get('subtotal') or 0):.2f}" + "{/left}")
    lineas.append("--------------------------------")
    if data.get("descuento"):
        lineas.append("{left}Descuento: -$" + f"{float(data['descuento']):.2f}" + "{/left}")
    if data.get("iva"):
        lineas.append("{left}IVA: $" + f"{float(data['iva']):.2f}" + "{/left}")
    lineas.append("{b}{w}TOTAL $" + f"{float(data.get('total') or 0):.2f}" + "{/w}{/b}")
    lineas.append("{br}{center}{s}Pagado con tarjeta - Mercado Pago{/s}{/center}{br}{br}")
    texto = "{br}".join(lineas)
    while len(texto) < 100:          # mínimo que exige la API
        texto += "{br}"
    return texto[:4096]


mp_point = MercadoPagoPointService()
