import time
import logging
import httpx
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# PaymentMethodInt из документации Platega
PAYMENT_METHOD_SBP = 2
PAYMENT_METHOD_ERIP = 3
PAYMENT_METHOD_CARD = 11
PAYMENT_METHOD_INTERNATIONAL = 12
PAYMENT_METHOD_CRYPTO = 13


@dataclass
class PlategaTransaction:
    transaction_id: str
    redirect_url: str
    status: str
    amount: str


class Platega:
    def __init__(self, merchant_id: str, secret: str):
        self.base = "https://app.platega.io/"
        self.headers = {
            "X-MerchantId": merchant_id,
            "X-Secret": secret,
            "Content-Type": "application/json",
        }

    async def create_payment(
        self,
        amount: float,
        payment_method: int,
        description: str = "",
        return_url: str = "",
        payload: str = "",
    ) -> Optional[PlategaTransaction]:
        body = {
            "paymentMethod": payment_method,
            "paymentDetails": {
                "amount": float(amount),
                "currency": "RUB",
            },
            "description": description,
            "return": return_url,
            "failedUrl": return_url,
        }
        if payload:
            body["payload"] = payload
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base}transaction/process",
                headers=self.headers,
                json=body,
            )
            if resp.status_code != 200:
                logger.error(f"Platega createPayment failed: {resp.status_code} {resp.text}")
                return None
            data = resp.json()
            return PlategaTransaction(
                transaction_id=data["transactionId"],
                redirect_url=data["redirect"],
                status=data.get("status", "PENDING"),
                amount=str(data.get("paymentDetails", amount)),
            )

    async def check_payment(self, transaction_id: str) -> Optional[PlategaTransaction]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base}transaction/{transaction_id}",
                headers=self.headers,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            amount = ""
            details = data.get("paymentDetails")
            if isinstance(details, dict):
                amount = str(details.get("amount", ""))
            elif isinstance(details, str):
                amount = details
            return PlategaTransaction(
                transaction_id=data["id"],
                redirect_url=data.get("payformSuccessUrl", ""),
                status=data.get("status", "PENDING"),
                amount=amount,
            )


@dataclass
class CryptoInvoice:
    invoice_id: int
    pay_url: str
    status: str
    amount: str


class CryptoBot:
    def __init__(self, token: str):
        self.token = token
        self.base = "https://pay.crypt.bot/api"
        self.headers = {"Crypto-Pay-API-Token": token}
        self._rate_cache: tuple[float, float] | None = None

    async def get_usdt_rate(self) -> float:
        now = time.time()
        if self._rate_cache and now - self._rate_cache[1] < 300:
            return self._rate_cache[0]
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "tether", "vs_currencies": "rub"},
                timeout=10,
            )
            data = resp.json()
            rate = float(data["tether"]["rub"])
            self._rate_cache = (rate, now)
            return rate

    async def create_invoice(
        self, amount: float, description: str = ""
    ) -> Optional[CryptoInvoice]:
        async with httpx.AsyncClient() as client:
            payload = {
                "amount": str(amount),
                "currency_type": "crypto",
                "asset": "USDT",
                "description": description,
                "expires_in": 300,
            }
            resp = await client.post(
                f"{self.base}/createInvoice",
                headers=self.headers,
                json=payload,
            )
            try:
                data = resp.json()
            except Exception:
                data = {}
            if data.get("ok"):
                result = data["result"]
                return CryptoInvoice(
                    invoice_id=result["invoice_id"],
                    pay_url=result["pay_url"],
                    status=result["status"],
                    amount=result["amount"],
                )
            logger.error(f"CryptoBot createInvoice failed: {resp.status_code} {data}")
            return None

    async def check_invoice(self, invoice_id: int) -> Optional[CryptoInvoice]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base}/getInvoices",
                headers=self.headers,
                params={"invoice_ids": str(invoice_id)},
            )
            data = resp.json()
            if data.get("ok") and data.get("result", {}).get("items"):
                item = data["result"]["items"][0]
                return CryptoInvoice(
                    invoice_id=item["invoice_id"],
                    pay_url=item.get("pay_url", ""),
                    status=item["status"],
                    amount=item["amount"],
                )
            return None
