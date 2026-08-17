import os
import json
from dataclasses import dataclass, field


@dataclass
class Plan:
    name: str
    price: float
    days: int
    traffic_gb: int = 0
    base_devices: int = 3
    extra_device_price: float = 50.0


@dataclass
class Config:
    bot_token: str
    bot_username: str
    admin_ids: list[int]
    xui_url: str
    xui_username: str
    xui_password: str
    xui_inbound_ids: list[int]
    sub_url_template: str
    platega_merchant_id: str = ""
    platega_secret: str = ""
    crypto_bot_token: str = ""
    currency: str = "RUB"
    platega_methods: list[int] = field(default_factory=lambda: [2, 11])
    support_username: str = ""
    plans: list[Plan] = field(default_factory=list)

    @property
    def has_payment(self) -> bool:
        return bool(self.platega_merchant_id and self.platega_secret) or bool(self.crypto_bot_token)

    @property
    def has_platega(self) -> bool:
        return bool(self.platega_merchant_id and self.platega_secret)

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

    xui_inbound_ids = []
    raw = os.getenv("XUI_INBOUND_IDS", "")
    if raw:
        for val in raw.split(","):
            val = val.strip()
            if val:
                try:
                    xui_inbound_ids.append(int(val))
                except ValueError:
                    pass
    else:
        xui_inbound_ids = [int(os.getenv("XUI_INBOUND_ID", "1"))]

    platega_methods = []
    for val in os.getenv("PLATEGA_METHODS", "2,11").split(","):
        val = val.strip()
        if val:
            try:
                platega_methods.append(int(val))
            except ValueError:
                pass
    if not platega_methods:
        platega_methods = [2, 11]

    return Config(
        bot_token=os.getenv("BOT_TOKEN", ""),
        bot_username=os.getenv("BOT_USERNAME", ""),
        admin_ids=admin_ids,
        xui_url=os.getenv("XUI_URL", ""),
        xui_username=os.getenv("XUI_USERNAME", ""),
        xui_password=os.getenv("XUI_PASSWORD", ""),
        xui_inbound_ids=xui_inbound_ids,
        sub_url_template=os.getenv("SUB_URL_TEMPLATE", ""),
        platega_merchant_id=os.getenv("PLATEGA_MERCHANT_ID", ""),
        platega_secret=os.getenv("PLATEGA_SECRET", ""),
        crypto_bot_token=os.getenv("CRYPTO_BOT_TOKEN", ""),
        currency=os.getenv("CURRENCY", "RUB"),
        platega_methods=platega_methods,
        support_username=os.getenv("SUPPORT_USERNAME", ""),
        plans=plans,
    )
