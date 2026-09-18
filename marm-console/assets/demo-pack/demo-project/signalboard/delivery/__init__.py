"""Local-only delivery adapter."""

from .outbox import queue_digest

__all__ = ["queue_digest"]
