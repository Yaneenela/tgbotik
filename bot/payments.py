import uuid
import base64
import httpx
from dataclasses import dataclass
from typing import Optional


@dataclass
class YooPayment:
    payment_id: str
    confirmation_url: str
    status: str
    amount: str


class YooKassa:
    def __init__(self, shop_id: str, secret_key: str):
        self.shop_id = shop_id
        self.secret_key = secret_key
        auth_str = f"{shop_id}:{secret_key}"
        self.auth_header = f"Basic {base64.b64encode(auth_str.encode()).decode()}"
        self.base = "https://api.yookassa.ru/v3"

    async def create_payment(
        self, amount: float, description: str = "", return_url: str = ""
    ) -> Optional[YooPayment]:
        idempotence_key = str(uuid.uuid4())
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base}/payments",
                headers={
                    "Authorization": self.auth_header,
                    "Idempotence-Key": idempotence_key,
                    "Content-Type": "application/json",
                },
                json={
                    "amount": {
                        "value": f"{amount:.2f}",
                        "currency": "RUB",
                    },
                    "confirmation": {
                        "type": "redirect",
                        "return_url": return_url,
                    },
                    "capture": True,
                    "description": description,
                },
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            return YooPayment(
                payment_id=data["id"],
                confirmation_url=data["confirmation"]["confirmation_url"],
                status=data["status"],
                amount=data["amount"]["value"],
            )

    async def check_payment(self, payment_id: str) -> Optional[YooPayment]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base}/payments/{payment_id}",
                headers={
                    "Authorization": self.auth_header,
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            return YooPayment(
                payment_id=data["id"],
                confirmation_url="",
                status=data["status"],
                amount=data["amount"]["value"],
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

    async def create_invoice(
        self, amount: float, description: str = ""
    ) -> Optional[CryptoInvoice]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base}/createInvoice",
                headers=self.headers,
                json={
                    "amount": str(amount),
                    "currency_type": "crypto",
                    "accepted_assets": ["USDT"],
                    "description": description,
                },
            )
            data = resp.json()
            if data.get("ok"):
                result = data["result"]
                return CryptoInvoice(
                    invoice_id=result["invoice_id"],
                    pay_url=result["pay_url"],
                    status=result["status"],
                    amount=result["amount"],
                )
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
