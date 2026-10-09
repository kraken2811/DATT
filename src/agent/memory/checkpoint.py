"""Checkpointer and short-term memory management for LangGraph Agent."""

import logging
import os
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from src.agent.config import agent_config
from src.agent.security import persistent_history_required

logger = logging.getLogger("datt.agent.memory")

_checkpointer_instance: BaseCheckpointSaver | None = None


def get_postgres_connection_string() -> str | None:
    """Retrieve raw PostgreSQL connection string formatted for psycopg."""
    url = os.environ.get("DATT_DATABASE_URL")
    if not url:
        from pathlib import Path
        env_file = Path(__file__).resolve().parent.parent.parent.parent / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("DATT_DATABASE_URL="):
                    url = line.split("=", 1)[1].strip().strip("'\"")
    if url and ("postgresql" in url or "postgres" in url):
        # Convert sqlalchemy dialect format to standard psycopg URL
        clean_url = url.replace("postgresql+psycopg://", "postgresql://")
        return clean_url
    return None


_pg_pool: Any = None


class CheckpointUnavailable(RuntimeError):
    """Persistent history is required but cannot be verified; message contains no driver details."""


def validate_checkpointer(checkpointer):
    if persistent_history_required():
        from langgraph.checkpoint.postgres import PostgresSaver
        if not isinstance(checkpointer, PostgresSaver):
            raise CheckpointUnavailable('PostgreSQL conversation history is required')
    return checkpointer


def get_checkpointer(force_memory: bool = False) -> BaseCheckpointSaver:
    """Create or return checkpointer instance.

    Persistent deployments require PostgresSaver. MemorySaver is permitted only when
    persistent conversation history is not required.
    """
    global _checkpointer_instance, _pg_pool
    if _checkpointer_instance is not None and not force_memory:
        return validate_checkpointer(_checkpointer_instance)

    if force_memory:
        return validate_checkpointer(MemorySaver())

    conn_str = get_postgres_connection_string()
    if conn_str:
        try:
            from psycopg_pool import ConnectionPool
            from psycopg.rows import dict_row
            from langgraph.checkpoint.postgres import PostgresSaver

            if _pg_pool is None:
                _pg_pool = ConnectionPool(
                    conn_str,
                    open=False,
                    min_size=1,
                    max_size=5,
                    check=ConnectionPool.check_connection,
                    max_idle=60.0,
                    kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                )
                _pg_pool.open(wait=True, timeout=agent_config.timeout_seconds)

            saver = PostgresSaver(_pg_pool)
            saver.setup()
            logger.info("PostgresSaver checkpointer initialized successfully with connection pool")
            _checkpointer_instance = saver
            return saver
        except Exception as exc:
            logger.error("Failed to initialize PostgresSaver (%s)", type(exc).__name__)
            if _pg_pool is not None:
                failed_pool = _pg_pool
                _pg_pool = None
                try:
                    failed_pool.close()
                except Exception as close_error:
                    logger.error('Failed to close checkpoint pool (%s)', type(close_error).__name__)
            if persistent_history_required():
                raise CheckpointUnavailable('Persistent conversation history unavailable') from None

    if persistent_history_required():
        raise CheckpointUnavailable('PostgreSQL conversation history is not configured')

    logger.info("Using MemorySaver checkpointer")
    _checkpointer_instance = MemorySaver()
    return _checkpointer_instance


def make_thread_config(thread_id: str, user_id: str = "default_user") -> dict[str, Any]:
    """Generate isolated execution configuration for LangGraph state graph."""
    clean_tid = (thread_id or "").strip() or "default"
    clean_uid = (user_id or "").strip() or "default_user"
    return {
        "configurable": {
            "thread_id": f"{clean_uid}:{clean_tid}",
            "user_id": clean_uid,
        },
        "recursion_limit": agent_config.recursion_limit,
    }


def clear_thread_checkpoint(thread_id: str, user_id: str = "default_user", *, session=None) -> bool:
    """Safely clear saved checkpoint state for a specific isolated user and thread."""
    config = make_thread_config(thread_id, user_id=user_id)
    internal_tid = config["configurable"]["thread_id"]

    if session is not None and session.bind.dialect.name == 'postgresql':
        # Same transaction as registry deletion: rollback restores both on any error.
        from sqlalchemy import text
        for table in ('checkpoint_writes', 'checkpoint_blobs', 'checkpoints'):
            session.execute(text('DELETE FROM ' + table + ' WHERE thread_id = :tid'), {'tid': internal_tid})
        return True

    checkpointer = get_checkpointer()
    if hasattr(checkpointer, "storage") and isinstance(checkpointer.storage, dict):
        # LangGraph stores pending writes separately from the checkpoint history.
        checkpointer.delete_thread(internal_tid)
        return True

    conn_str = get_postgres_connection_string()
    if conn_str:
        try:
            import psycopg
            with psycopg.connect(conn_str) as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM checkpoints WHERE thread_id = %s;", (internal_tid,))
                    cur.execute("DELETE FROM checkpoint_blobs WHERE thread_id = %s;", (internal_tid,))
                    cur.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s;", (internal_tid,))
                conn.commit()
            return True
        except Exception as exc:
            logger.error("Failed to clear PostgreSQL checkpoint (%s)", type(exc).__name__)
    return False
