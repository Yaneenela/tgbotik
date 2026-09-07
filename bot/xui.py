import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid as uuid_lib

import requests
from py3xui import Api, Client, Inbound
from pydantic import ConfigDict, Field


class XUIClient(Client):
    """Client model with 3x-UI v3.7.0 `limitHwid` (per-subscription HWID device limit).

    `limitIp` default is `-1` so that passing `limit_ip=0` (unlimited) is actually
    serialized by py3xui (which dumps with `exclude_defaults=True` and would drop
    the default value `0` otherwise).
    """

    limit_hwid: int = Field(default=0, alias="limitHwid")
    limit_ip: int = Field(default=-1, alias="limitIp")

    model_config = ConfigDict(populate_by_name=True, validate_by_alias=True)


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
            await self._ensure_login()
            return await asyncio.to_thread(func, *args, **kwargs)

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
        expiry = int((datetime.now(timezone.utc) + timedelta(days=days)).timestamp() * 1000)
        total_gb = traffic_gb * 1024**3 if traffic_gb > 0 else 0

        client = XUIClient(
            id=client_uuid,
            email=email,
            flow="xtls-rprx-vision",
            limit_ip=0,
            limit_hwid=device_count,
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
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        new_expiry = now_ms + additional_days * 86400000

        updated = XUIClient(
            id=client_uuid,
            email=email,
            flow="xtls-rprx-vision",
            limit_ip=0,
            limit_hwid=device_count,
            total_gb=0,
            expiry_time=new_expiry,
            enable=True,
            tg_id="",
            sub_id=client_uuid,
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

    def _hwid_request(self, method, endpoint: str) -> dict:
        client = self.api.client
        url = client._url(endpoint)
        response = client._request_with_retry(
            method, url, {"Accept": "application/json"}, json={}
        )
        return response.json()

    async def get_client_hwids(self, email: str) -> list[dict]:
        try:
            data = await self._call(self._hwid_request, requests.post, f"panel/api/clients/hwids/{email}")
            obj = data.get("obj")
            return obj if isinstance(obj, list) else []
        except Exception:
            return []

    async def delete_client_hwid(self, email: str, hwid_id: int) -> bool:
        try:
            await self._call(
                self._hwid_request, requests.delete, f"panel/api/clients/hwids/{email}/{hwid_id}"
            )
            return True
        except Exception:
            return False

    async def clear_client_hwids(self, email: str) -> bool:
        try:
            await self._call(self._hwid_request, requests.delete, f"panel/api/clients/hwids/{email}")
            return True
        except Exception:
            return False

    async def apply_device_limit(self, client_uuid: str, device_count: int):
        """Set the HWID device limit for an existing client, keeping its current
        expiry and traffic intact (used to migrate clients created with `limitIp`)."""
        selected = None
        inbounds = await self.get_inbounds()
        for inbound in inbounds:
            for client in (inbound.settings.clients or []):
                if str(client.id) == client_uuid:
                    selected = client
                    break
            if selected:
                break
        if selected is None:
            return

        updated = XUIClient(
            id=client_uuid,
            email=selected.email,
            flow="xtls-rprx-vision",
            limit_ip=0,
            limit_hwid=device_count,
            total_gb=selected.total_gb or 0,
            expiry_time=selected.expiry_time or 0,
            enable=selected.enable if selected.enable is not None else True,
            tg_id="",
            sub_id=selected.sub_id or client_uuid,
        )
        await self._call(self.api.client.update, client_uuid, updated)
