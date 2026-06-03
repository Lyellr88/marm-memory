"""Serialized write queue for MARM memory writes."""

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional


@dataclass
class MemoryWriteRequest:
    content: str
    session: str
    context_type: str
    metadata: Optional[dict]
    future: asyncio.Future


@dataclass
class CallableWriteRequest:
    """Generic write request for non-store_memory operations (e.g. compaction apply)."""

    func: Callable[..., Awaitable[Any] | Any]
    args: tuple
    kwargs: dict
    future: asyncio.Future


class WriteQueue:
    """Serialize memory writes through one async worker."""

    def __init__(self, memory, max_size: int = 100):
        self.memory = memory
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=max_size)
        self._worker_task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._worker_task and not self._worker_task.done():
            return
        self._stopping = False
        self._worker_task = asyncio.create_task(self._worker(), name="marm-write-queue")

    async def stop(self) -> None:
        self._stopping = True
        await self.queue.join()
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    async def put(
        self,
        content: str,
        session: str,
        context_type: str = "general",
        metadata: Optional[dict] = None,
    ) -> str:
        if self._stopping:
            raise RuntimeError("write queue is shutting down")
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        await self.queue.put(
            MemoryWriteRequest(content, session, context_type, metadata, future)
        )
        return await future

    async def put_callable(
        self, func: Callable[..., Awaitable[Any] | Any], *args: Any, **kwargs: Any
    ) -> Any:
        """Enqueue any async callable to be executed in write-queue order."""
        if self._stopping:
            raise RuntimeError("write queue is shutting down")
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        await self.queue.put(CallableWriteRequest(func, args, kwargs, future))
        return await future

    async def _worker(self) -> None:
        while True:
            request = await self.queue.get()
            try:
                if isinstance(request, MemoryWriteRequest):
                    result = await self.memory.store_memory(
                        request.content,
                        request.session,
                        request.context_type,
                        request.metadata,
                    )
                elif isinstance(request, CallableWriteRequest):
                    maybe_result = request.func(*request.args, **request.kwargs)
                    result = (
                        await maybe_result
                        if inspect.isawaitable(maybe_result)
                        else maybe_result
                    )
                else:
                    raise TypeError(f"Unsupported queue request type: {type(request)!r}")
                self._resolve(request.future, result)
            except Exception as exc:
                if hasattr(request, "future"):
                    self._reject(request.future, exc)
            finally:
                self.queue.task_done()

    @staticmethod
    def _resolve(future: asyncio.Future, value: Any) -> None:
        if not future.done():
            future.set_result(value)

    @staticmethod
    def _reject(future: asyncio.Future, exc: Exception) -> None:
        if not future.done():
            future.set_exception(exc)
