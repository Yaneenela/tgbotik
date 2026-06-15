import os
import json
from dataclasses import dataclass, field


@dataclass
class Plan:
    name: str
    price: float
    days: int
    traffic_gb: int = 0


@dataclass
class Config:
    bot_token: str
    bot_username: str
    admin_ids: list[int]
    xui_url: str
    xui_username: str
    xui_password: str
    xui_inbound_id: int
    sub_url_template: str
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    crypto_bot_token: str = ""
    currency: str = "RUB"
    plans: list[Plan] = field(default_factory=list)

    @property
    def sub_url(self) -> str:
        return self.sub_url_template.rstrip("/")

    def make_sub_url(self, uuid_str: str) -> str:
        return self.sub_url.replace("{uuid}", uuid_str)


def load_config() -> Config:
    try:
        plans_data = json.loads(os.getenv("PLANS", "[]"))
        plans = [Plan(**p) for p in plans_data]
    except (json.JSONDecodeError, TypeError, KeyError):
        plans = []

    admin_ids = []
    for val in os.getenv("ADMIN_IDS", "").split(","):
        val = val.strip()
        if val:
            try:
                admin_ids.append(int(val))
            except ValueError:
                pass

    return Config(
        bot_token=os.getenv("BOT_TOKEN", ""),
        bot_username=os.getenv("BOT_USERNAME", ""),
        admin_ids=admin_ids,
        xui_url=os.getenv("XUI_URL", ""),
        xui_username=os.getenv("XUI_USERNAME", ""),
        xui_password=os.getenv("XUI_PASSWORD", ""),
        xui_inbound_id=int(os.getenv("XUI_INBOUND_ID", "1")),
        sub_url_template=os.getenv("SUB_URL_TEMPLATE", ""),
        yookassa_shop_id=os.getenv("YOOKASSA_SHOP_ID", ""),
        yookassa_secret_key=os.getenv("YOOKASSA_SECRET_KEY", ""),
        crypto_bot_token=os.getenv("CRYPTO_BOT_TOKEN", ""),
        currency=os.getenv("CURRENCY", "RUB"),
        plans=plans,
    )
