"""Thin wrapper over Hoverfly Admin API (port 8888 by default).

Docs: https://docs.hoverfly.io/en/latest/pages/reference/api/api.html
"""
from __future__ import annotations
from typing import Literal

import httpx

Mode = Literal["capture", "simulate", "spy", "synthesize", "modify"]


class HoverflyClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def get_simulation(self) -> dict:
        r = self._client.get("/api/v2/simulation")
        r.raise_for_status()
        return r.json()

    def put_simulation(self, simulation: dict) -> None:
        r = self._client.put("/api/v2/simulation", json=simulation)
        r.raise_for_status()

    def delete_simulation(self) -> None:
        r = self._client.delete("/api/v2/simulation")
        r.raise_for_status()

    def set_mode(self, mode: Mode) -> None:
        r = self._client.put("/api/v2/hoverfly/mode", json={"mode": mode})
        r.raise_for_status()

    def close(self) -> None:
        self._client.close()
