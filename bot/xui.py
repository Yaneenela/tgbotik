import asyncio
from datetime import datetime, timedelta
from typing import Optional
import uuid as uuid_lib

from py3xui import Api, Client, Inbound


class XUIManager:
    def __init__(self, url: str, username: str, password: str):
        self.api = Api(url, username=username, password=password)
        self._logged_in = False

    async def _ensure_login(self):
        if not self._logged_in:
            await asyncio.to_thread(self.api.login)
            self._logged_in = True

    async def _call(self, func, *args, **kwargs):
        await self._ensure_login()
        try:
            return await asyncio.to_thread(func, *args, **kwargs)
        except Exception:
            self._logged_in = False
            raise

    async def get_inbounds(self) -> list[Inbound]:
        return await self._call(self.api.inbound.get_list)

    async def get_inbound(self, inbound_id: int) -> Optional[Inbound]:
        inbounds = await self.get_inbounds()
        for ib in inbounds:
            if ib.id == inbound_id:
                return ib
        return None

    async def create_client(
        self, inbound_ids: list[int], email: str, days: int, traffic_gb: int = 0, device_count: int = 3
    ) -> tuple[str, Client]:
        client_uuid = str(uuid_lib.uuid4())
        expiry = int((datetime.now() + timedelta(days=days)).timestamp() * 1000)
        total_gb = traffic_gb * 1024**3 if traffic_gb > 0 else 0

        client = Client(
            id=client_uuid,
            email=email,
            flow="xtls-rprx-vision",
            limit_ip=device_count,
            total_gb=total_gb,
            expiry_time=expiry,
            enable=True,
            tg_id="",
            sub_id=client_uuid,
        )

        for inbound_id in inbound_ids:
            await self._call(self.api.client.add, inbound_id, [client])

        return client_uuid, client

    async def delete_client(self, client_uuid: str, inbound_ids: list[int]):
        for inbound_id in inbound_ids:
            try:
                await self._call(self.api.client.delete, inbound_id, client_uuid)
            except Exception:
                pass

    async def update_client_expiry(
        self, client_uuid: str, email: str, additional_days: int, device_count: int = 3
    ):
        now_ms = int(datetime.now().timestamp() * 1000)
        new_expiry = now_ms + additional_days * 86400000

        updated = Client(
            id=client_uuid,
            email=email,
            expiry_time=new_expiry,
            enable=True,
            flow="xtls-rprx-vision",
            limit_ip=device_count,
        )
        await self._call(self.api.client.update, client_uuid, updated)

    async def get_client_traffic(self, client_uuid: str) -> dict:
        try:
            clients = await self._call(self.api.client.get_traffic_by_id, client_uuid)
            if clients:
                c = clients[0]
                return {"up": getattr(c, "up", 0), "down": getattr(c, "down", 0)}
        except Exception:
            pass
        return {"up": 0, "down": 0}

    async def get_client_ips(self, email: str) -> list[str]:
        try:
            return await self._call(self.api.client.get_ips, email)
        except Exception:
            return []

    async def reset_client_ips(self, email: str):
        try:
            await self._call(self.api.client.reset_ips, email)
        except Exception:
            pass
