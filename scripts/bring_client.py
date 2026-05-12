#!/usr/bin/env python3
"""Synchronous wrapper around the async `bring-api` package.

The rest of the codebase is sync. Rather than make every caller deal
with asyncio, this module runs a single event loop internally and exposes
blocking methods.

Errors from the underlying library propagate as exceptions — callers
decide how to handle them (the push script logs and continues; the
regen guard logs and continues).
"""
from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

import aiohttp
from bring_api import Bring


class BringClient:
    """Sync wrapper. Call login() after construction; close() when done.

    Intended usage:
        with BringClient(email, password) as bring:
            uuid = bring.find_list_by_name("Groceries")
            items = bring.get_items(uuid)
            bring.add_item(uuid, "milk", "1 gal")
    """

    def __init__(self, email: str, password: str) -> None:
        self._email = email
        self._password = password
        self._loop = asyncio.new_event_loop()
        self._session: aiohttp.ClientSession | None = None
        self._bring: Bring | None = None

    def __enter__(self) -> "BringClient":
        self.login()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _run(self, coro: Any) -> Any:
        return self._loop.run_until_complete(coro)

    def login(self) -> None:
        async def _do() -> None:
            self._session = aiohttp.ClientSession()
            self._bring = Bring(self._session, self._email, self._password)
            await self._bring.login()

        self._run(_do())

    def close(self) -> None:
        async def _do() -> None:
            if self._session is not None:
                await self._session.close()

        try:
            self._run(_do())
        finally:
            self._loop.close()

    def find_list_by_name(self, name: str) -> str | None:
        """Return the list's UUID, or None if no list has that exact name."""
        assert self._bring is not None, "call login() first"
        resp = self._run(self._bring.load_lists())
        for lst in resp.lists:
            if lst.name == name:
                return lst.listUuid
        return None

    def get_items(self, list_uuid: str) -> dict[str, list[dict]]:
        """Return {'active': [...], 'recent': [...]}.

        Active items are on the shopping list (to buy). Recent items are
        recently purchased (checked off). Each item is converted to a
        plain dict so callers can use `.get()` without worrying about
        the library's dataclass types.
        """
        assert self._bring is not None, "call login() first"
        resp = self._run(self._bring.get_list(list_uuid))
        return {
            "active": [dataclasses.asdict(p) for p in resp.items.purchase],
            "recent": [dataclasses.asdict(p) for p in resp.items.recently],
        }

    def add_item(self, list_uuid: str, name: str, spec: str = "") -> None:
        assert self._bring is not None, "call login() first"
        self._run(self._bring.save_item(list_uuid, name, spec))

    def remove_item(self, list_uuid: str, name: str) -> None:
        assert self._bring is not None, "call login() first"
        self._run(self._bring.remove_item(list_uuid, name))
