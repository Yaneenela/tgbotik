import httpx
from dataclasses import dataclass
from typing import Optional


@dataclass
class Invoice:
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
        self, amount: float, currency: str = "USD", description: str = ""
    ) -> Optional[Invoice]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base}/createInvoice",
                headers=self.headers,
                json={
                    "amount": str(amount),
                    "currency_type": "crypto",
                    "fiat": currency,
                    "accepted_assets": ["USDT"],
                    "description": description,
                },
            )
            data = resp.json()
            if data.get("ok"):
                result = data["result"]
                return Invoice(
                    invoice_id=result["invoice_id"],
                    pay_url=result["pay_url"],
                    status=result["status"],
                    amount=result["amount"],
                )
            return None

    async def check_invoice(self, invoice_id: int) -> Optional[Invoice]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base}/getInvoices",
                headers=self.headers,
                params={"invoice_ids": str(invoice_id)},
            )
            data = resp.json()
            if data.get("ok") and data.get("result", {}).get("items"):
                item = data["result"]["items"][0]
                return Invoice(
                    invoice_id=item["invoice_id"],
                    pay_url=item.get("pay_url", ""),
                    status=item["status"],
                    amount=item["amount"],
                )
            return None

    async def get_balance(self) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base}/getBalance",
                headers=self.headers,
            )
            data = resp.json()
            if data.get("ok"):
                return {b["currency_code"]: float(b["available"]) for b in data["result"]}
            return {}
