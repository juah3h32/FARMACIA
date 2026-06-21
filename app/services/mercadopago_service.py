import requests
import threading
import time
from typing import Callable, Optional

MP_BASE = "https://api.mercadopago.com"

_TERMINAL_STATES = {"CANCELED", "ERROR", "ABANDONED"}


class MercadoPagoPointService:
    def __init__(self):
        self.access_token: str = ""
        self.device_id: str = ""

    def configure(self, access_token: str, device_id: str):
        self.access_token = access_token.strip()
        self.device_id = device_id.strip()

    @property
    def enabled(self) -> bool:
        return bool(self.access_token and self.device_id)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def get_devices(self) -> list:
        r = requests.get(
            f"{MP_BASE}/point/integration-api/devices",
            headers=self._headers(), timeout=10
        )
        r.raise_for_status()
        data = r.json()
        return data.get("devices", [])

    def set_pdv_mode(self, device_id: Optional[str] = None) -> bool:
        did = device_id or self.device_id
        r = requests.patch(
            f"{MP_BASE}/point/integration-api/devices/{did}",
            headers=self._headers(),
            json={"operating_mode": "PDV"},
            timeout=10
        )
        return r.status_code == 200

    def cancel_current_intent(self) -> bool:
        try:
            r = requests.delete(
                f"{MP_BASE}/point/integration-api/devices/{self.device_id}/payment-intents",
                headers=self._headers(), timeout=10
            )
            return r.status_code in (200, 204)
        except Exception:
            return False

    def create_payment_intent(self, amount: float, reference: str) -> dict:
        """amount en pesos MXN → convierte a centavos"""
        amount_cents = int(round(amount * 100))
        r = requests.post(
            f"{MP_BASE}/point/integration-api/devices/{self.device_id}/payment-intents",
            headers=self._headers(),
            json={
                "amount": amount_cents,
                "additional_info": {
                    "external_reference": reference,
                    "print_on_terminal": True,
                }
            },
            timeout=15
        )
        r.raise_for_status()
        return r.json()

    def get_payment_intent(self, intent_id: str) -> dict:
        r = requests.get(
            f"{MP_BASE}/point/integration-api/payment-intents/{intent_id}",
            headers=self._headers(), timeout=10
        )
        r.raise_for_status()
        return r.json()

    def poll_payment(
        self,
        intent_id: str,
        on_approved: Callable[[dict], None],
        on_rejected: Callable[[str], None],
        on_error: Callable[[str], None],
        timeout_seconds: int = 120,
        interval: float = 2.5,
    ):
        """Polls en hilo de fondo. Llama un callback cuando termina."""
        def _poll():
            elapsed = 0.0
            while elapsed < timeout_seconds:
                try:
                    data = self.get_payment_intent(intent_id)
                    state = data.get("state", "")
                    if state == "PROCESSED":
                        payment = data.get("payment", {})
                        p_state = payment.get("state", "")
                        if p_state == "APPROVED":
                            on_approved({
                                "mp_payment_id": payment.get("id"),
                                "mp_intent_id": intent_id,
                            })
                        else:
                            on_rejected(f"Pago no aprobado: {p_state}")
                        return
                    elif state in _TERMINAL_STATES:
                        on_rejected(f"Terminal: {state}")
                        return
                except Exception:
                    pass  # error transitorio — seguir polling
                time.sleep(interval)
                elapsed += interval
            on_error("Tiempo agotado (120 s) esperando respuesta de terminal")

        threading.Thread(target=_poll, daemon=True).start()


mp_point = MercadoPagoPointService()
