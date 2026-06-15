import os
import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Plan:
    name: str
    price: float
    days: int
    traffic_gb: int = 0


@dataclass
class Config:
    bot_token: str
    admin_ids: list[int]
    xui_url: str
    xui_username: str
    xui_password: str
    xui_inbound_id: int
    sub_url_template: str
    crypto_bot_token: str = ""
    usdt_address: str = ""
    usdt_network: str = "TRC20"
    currency: str = "USD"
    plans: list[Plan] = field(default_factory=list)

    @property
    def sub_url(self) -> str:
        return self.sub_url_template.rstrip("/")

    def make_sub_url(self, uuid_str: str) -> str:
        return self.sub_url.replace("{uuid}", uuid_str)


def load_config() -> Config:
    plans_data = json.loads(os.getenv("PLANS", "[]"))
    plans = [Plan(**p) for p in plans_data]

    return Config(
        bot_token=os.getenv("BOT_TOKEN", ""),
        admin_ids=[int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()],
        xui_url=os.getenv("XUI_URL", ""),
        xui_username=os.getenv("XUI_USERNAME", ""),
        xui_password=os.getenv("XUI_PASSWORD", ""),
        xui_inbound_id=int(os.getenv("XUI_INBOUND_ID", "1")),
        sub_url_template=os.getenv("SUB_URL_TEMPLATE", ""),
        crypto_bot_token=os.getenv("CRYPTO_BOT_TOKEN", ""),
        usdt_address=os.getenv("USDT_ADDRESS", ""),
        usdt_network=os.getenv("USDT_NETWORK", "TRC20"),
        currency=os.getenv("CURRENCY", "USD"),
        plans=plans,
    )
