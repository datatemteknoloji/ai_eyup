"""Sohbet yolu için ayrılmış iş parçacığı havuzu (Adım 11).

Neden: event döngüsünü bloklayan senkron işler (yönlendirme ipucu LLM'i, RAG SQL araması, OCP API,
turn oluşturma, Redis XREAD) `asyncio.to_thread` ile varsayılan yürütücüye (150 işçili `_SSH_EXECUTOR`)
taşındı. Ama o havuz arka plan işleriyle (ör. binlerce `search_and_sync_vm_details`, 10 sn bağlantı
zaman aşımı) dolabiliyor; sohbet isteği başlatma/SSE teslimi onların kuyruğunda beklerdi.
Sohbet için ayrı havuz → arka plan fırtınası sohbeti kilitlemez. Bağlam değişkenleri
(`trace_scope`, `cq_trace`, `cancel`) `asyncio.to_thread` ile aynı şekilde kopyalanır.
"""
from __future__ import annotations

import asyncio
import contextvars
import functools
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

T = TypeVar("T")

CHAT_IO_WORKERS = 96
CHAT_EXECUTOR = ThreadPoolExecutor(max_workers=CHAT_IO_WORKERS, thread_name_prefix="chat_io")


async def run_chat_io(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """`asyncio.to_thread` eşdeğeri; ama sohbete ayrılmış havuzda çalışır."""
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    return await loop.run_in_executor(CHAT_EXECUTOR, functools.partial(ctx.run, func, *args, **kwargs))
