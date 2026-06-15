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

    async def get_inbounds(self) -> list[Inbound]:
        await self._ensure_login()
        return await asyncio.to_thread(self.api.inbound.list)

    async def get_inbound(self, inbound_id: int) -> Optional[Inbound]:
        inbounds = await self.get_inbounds()
        for ib in inbounds:
            if ib.id == inbound_id:
                return ib
        return None

    async def create_client(
        self, inbound_id: int, email: str, days: int, traffic_gb: int = 0
    ) -> tuple[str, Client]:
        await self._ensure_login()
        client_uuid = str(uuid_lib.uuid4())
        expiry = int((datetime.now() + timedelta(days=days)).timestamp() * 1000)
        total_gb = traffic_gb * 1024**3 if traffic_gb > 0 else 0

        client = Client(
            id=client_uuid,
            email=email,
            flow="xtls-rprx-vision",
            limit_ip=0,
            total_gb=total_gb,
            expiry_time=expiry,
            enable=True,
            tg_id="",
            sub_id=client_uuid,
        )

        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            raise ValueError(f"Inbound {inbound_id} not found")

        clients = inbound.settings.get("clients", []) if inbound.settings else []
        clients.append(client.dict())
        inbound.settings["clients"] = clients

        await asyncio.to_thread(self.api.inbound.update, inbound_id, inbound)
        return client_uuid, client

    async def delete_client(self, inbound_id: int, client_uuid: str):
        await self._ensure_login()
        await asyncio.to_thread(self.api.client.delete, inbound_id, client_uuid)

    async def update_client_expiry(
        self, inbound_id: int, client_uuid: str, additional_days: int
    ):
        await self._ensure_login()
        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            return

        clients = inbound.settings.get("clients", []) if inbound.settings else []
        for c in clients:
            if c.get("id") == client_uuid:
                current_expiry = c.get("expiryTime", 0)
                now_ms = int(datetime.now().timestamp() * 1000)
                if current_expiry > now_ms:
                    new_expiry = current_expiry + additional_days * 86400000
                else:
                    new_expiry = now_ms + additional_days * 86400000
                c["expiryTime"] = new_expiry
                c["enable"] = True
                break

        inbound.settings["clients"] = clients
        await asyncio.to_thread(self.api.inbound.update, inbound_id, inbound)

    async def get_client_traffic(self, client_uuid: str) -> dict:
        await self._ensure_login()
        try:
            traffic = await asyncio.to_thread(self.api.client.get_traffic, client_uuid)
            return traffic
        except Exception:
            return {"up": 0, "down": 0}
