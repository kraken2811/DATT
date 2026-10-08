"""Resolve the single migration head recorded by this checkout's Alembic scripts."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


ALEMBIC_INI = Path(__file__).resolve().parent / "alembic.ini"


class MigrationHeadError(RuntimeError):
    """The repository has no unambiguous migration target."""


def repository_head(config=None):
    config = config if config is not None else Config(str(ALEMBIC_INI))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if not heads:
        raise MigrationHeadError("Repository has no Alembic head")
    if len(heads) > 1:
        raise MigrationHeadError("Repository has multiple Alembic heads")
    return script.get_current_head()
