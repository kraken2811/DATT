"""Configuration and settings for DATT AI Agent and RAG Subsystem."""

import os
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")


@dataclass
class AgentConfig:
    """Agent and RAG runtime settings."""

    # Centralized LLM configuration
    llm_provider: str = os.getenv("DATT_AGENT_LLM_PROVIDER") or os.getenv("AGENT_LLM_PROVIDER", "mock")
    model_name: str = os.getenv("DATT_AGENT_LLM_MODEL") or os.getenv("AGENT_MODEL_NAME", "gpt-4o-mini")
    temperature: float = float(os.getenv("DATT_AGENT_LLM_TEMPERATURE") or os.getenv("AGENT_TEMPERATURE", "0.1"))
    timeout_seconds: float = float(os.getenv("DATT_AGENT_LLM_TIMEOUT_SECONDS") or os.getenv("AGENT_TIMEOUT_SEC", "30.0"))
    max_retries: int = int(os.getenv("DATT_AGENT_LLM_MAX_RETRIES", "3"))

    # Optional Fallback LLM
    fallback_provider: str | None = os.getenv("DATT_AGENT_LLM_FALLBACK_PROVIDER")
    fallback_model: str | None = os.getenv("DATT_AGENT_LLM_FALLBACK_MODEL")

    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    # Execution limits & safety
    recursion_limit: int = int(os.getenv("AGENT_RECURSION_LIMIT", "15"))
    execution_timeout_sec: float = float(os.getenv("AGENT_TIMEOUT_SEC", "30.0"))
    tool_timeout_sec: float = float(os.getenv("AGENT_TOOL_TIMEOUT_SEC", "10.0"))
    max_tool_repeats: int = int(os.getenv("AGENT_MAX_TOOL_REPEATS", "2"))
    max_tool_cycles: int = int(os.getenv("DATT_AGENT_MAX_TOOL_CYCLES") or os.getenv("AGENT_MAX_TOOL_CYCLES", "4"))
    max_total_tool_calls: int = int(os.getenv("DATT_AGENT_MAX_TOTAL_TOOL_CALLS") or os.getenv("AGENT_MAX_TOTAL_TOOL_CALLS", "8"))

    # Memory & Context trimming
    max_history_messages: int = int(os.getenv("AGENT_MAX_HISTORY_MESSAGES", "20"))
    trim_threshold_tokens: int = int(os.getenv("AGENT_TRIM_THRESHOLD_TOKENS", "4000"))

    # RAG Settings - Defaulting to Vietnamese-benchmarked multilingual model
    embedding_provider: str = os.getenv("DATT_AGENT_EMBEDDING_PROVIDER") or os.getenv("AGENT_EMBEDDING_PROVIDER", "fastembed")
    embedding_model: str = os.getenv("DATT_AGENT_EMBEDDING_MODEL") or os.getenv("AGENT_EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    embedding_dim: int = int(os.getenv("DATT_AGENT_EMBEDDING_DIM") or os.getenv("AGENT_EMBEDDING_DIM", "384"))
    rag_chunk_size: int = int(os.getenv("AGENT_RAG_CHUNK_SIZE", "800"))
    rag_chunk_overlap: int = int(os.getenv("AGENT_RAG_CHUNK_OVERLAP", "100"))
    rag_top_k: int = int(os.getenv("AGENT_RAG_TOP_K", "4"))
    rag_score_threshold: float = float(os.getenv("AGENT_RAG_SCORE_THRESHOLD", "0.50"))

    # Storage paths and Database connectivity
    docs_dir: Path = PROJECT_ROOT / "docs"
    database_url: str | None = os.getenv("DATT_DATABASE_URL")

    def get_database(self) -> Any:
        """Instantiate a Database instance bound directly to the resolved database URL."""
        from src.db.database import Database
        return Database(url=self.database_url)


agent_config = AgentConfig()
