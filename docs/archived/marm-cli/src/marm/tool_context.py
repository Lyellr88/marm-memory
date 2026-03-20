"""Shared tool context - Singleton pattern for database and semantic search

CRITICAL FIX: Prevents repeated instantiation of heavy dependencies.
Database and SemanticSearch are created once and reused across all tool calls.
"""

import logging
from typing import Optional
from .database import MARMDatabase
from .semantic import SemanticSearch

logger = logging.getLogger(__name__)


class ToolContext:
    """Singleton context for shared tool dependencies"""

    _instance: Optional['ToolContext'] = None
    _db: Optional[MARMDatabase] = None
    _semantic: Optional[SemanticSearch] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_database(cls) -> MARMDatabase:
        """Get shared database instance"""
        if cls._db is None:
            logger.info("Initializing shared MARMDatabase instance")
            cls._db = MARMDatabase()
        return cls._db

    @classmethod
    def get_semantic(cls) -> SemanticSearch:
        """Get shared semantic search instance (model loaded once)"""
        if cls._semantic is None:
            logger.info("Initializing shared SemanticSearch instance (loading model...)")
            cls._semantic = SemanticSearch()
        return cls._semantic

    @classmethod
    def close_all(cls):
        """Close all shared resources"""
        if cls._db:
            cls._db.close()
            cls._db = None
        cls._semantic = None  # Model will be garbage collected
        logger.info("Closed all shared tool context resources")


def get_shared_db() -> MARMDatabase:
    """Helper: Get shared database instance"""
    return ToolContext.get_database()


def get_shared_semantic() -> SemanticSearch:
    """Helper: Get shared semantic search instance"""
    return ToolContext.get_semantic()
