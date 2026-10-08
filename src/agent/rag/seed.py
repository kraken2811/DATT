"""Seed and synchronize project documentation into the knowledge base."""

import logging
from pathlib import Path

from src.agent.config import agent_config
from src.agent.rag.ingestion import IngestionService

logger = logging.getLogger("datt.agent.seed")


def seed_knowledge_base(docs_dir: Path | str | None = None, force_update: bool = False) -> int:
    """Ingest reference documentation from docs/ into PostgreSQL pgvector."""
    target_dir = Path(docs_dir) if docs_dir else agent_config.docs_dir
    if not target_dir.is_dir():
        logger.warning("Docs directory not found: %s", target_dir)
        return 0

    with IngestionService() as ingestion:
        results = ingestion.ingest_directory(
            target_dir,
            glob_patterns=["*.md", "*.txt"],
            force_update=force_update,
        )

    ingested = sum(1 for r in results if r.status in ("created", "updated", "skipped"))
    logger.info("Knowledge base seeding completed: %d files processed", ingested)
    return ingested


if __name__ == "__main__":
    import sys
    ROOT = Path(__file__).resolve().parent.parent.parent.parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    count = seed_knowledge_base(force_update=True)
    print(f"Seeded {count} documentation files into knowledge base.")
