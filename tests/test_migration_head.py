"""Migration startup checks against isolated SQLite databases and Alembic scripts."""

import json
from types import SimpleNamespace

from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError
import pytest

from scripts.colab_startup import Blocker, Startup
from src.db.migration_head import MigrationHeadError, repository_head
from src.ops import checks, cli


@pytest.fixture
def isolated_database(monkeypatch, tmp_path):
    monkeypatch.setenv("DATT_DATABASE_URL", "sqlite:///" + (tmp_path / "migration.db").as_posix())
    monkeypatch.setenv("DATT_REQUIRE_PERSISTENCE", "0")
    return Config("src/db/alembic.ini")


def test_database_already_at_current_head(isolated_database):
    command.upgrade(isolated_database, "head")
    result = checks.migrate()
    assert result["repository_head"] == repository_head(isolated_database)
    assert result["alembic_revision"] == result["repository_head"]
    assert result["alembic"] == "PASS"


def test_database_behind_head_is_upgraded(isolated_database):
    command.upgrade(isolated_database, "0011")
    assert checks.database_check()["alembic"] == "FAIL"
    result = checks.migrate()
    assert result["alembic_revision"] == repository_head(isolated_database)
    assert result["alembic"] == "PASS"


def test_skipped_upgrade_does_not_pass_revision_verification(isolated_database, monkeypatch):
    command.upgrade(isolated_database, "0011")
    monkeypatch.setattr(command, "upgrade", lambda *_args, **_kwargs: None)
    result = checks.migrate()
    assert result["alembic_revision"] == "0011"
    assert result["alembic"] == "FAIL"


def test_repository_head_changes_without_code_change(tmp_path):
    versions = tmp_path / "versions"
    versions.mkdir()
    config = Config()
    config.set_main_option("script_location", str(tmp_path))

    def add(revision, parent):
        (versions / f"{revision}.py").write_text(
            f"revision = {revision!r}\ndown_revision = {parent!r}\n",
            encoding="utf-8",
        )

    add("0013", None)
    assert repository_head(config) == "0013"
    add("0014", "0013")
    assert repository_head(config) == "0014"


def test_multiple_heads_are_an_explicit_blocker(monkeypatch, tmp_path):
    versions = tmp_path / "versions"
    versions.mkdir()
    config = Config()
    config.set_main_option("script_location", str(tmp_path))
    for revision, parent in (("0013", None), ("0014a", "0013"), ("0014b", "0013")):
        (versions / f"{revision}.py").write_text(
            f"revision = {revision!r}\ndown_revision = {parent!r}\n",
            encoding="utf-8",
        )
    with pytest.raises(MigrationHeadError, match="multiple Alembic heads"):
        repository_head(config)

    from src.db import migration_head
    monkeypatch.setattr(migration_head, "ALEMBIC_INI", tmp_path / "alembic.ini")
    (tmp_path / "alembic.ini").write_text(
        f"[alembic]\nscript_location = {tmp_path.as_posix()}\n", encoding="utf-8"
    )
    monkeypatch.setattr(Startup, "git_commit", staticmethod(lambda: "test"))
    startup = Startup({"runtime": "colab"})
    startup.completed = 4
    with pytest.raises(Blocker, match="multiple Alembic heads"):
        startup.run(5)
    assert startup.report["SYSTEM_READY"] == "NO"


def test_migration_failure_is_redacted_and_blocks_startup(
    isolated_database, monkeypatch, capsys
):
    def fail(*_args, **_kwargs):
        raise CommandError("PRIVATE_DATABASE_DETAIL")

    monkeypatch.setattr(command, "upgrade", fail)
    assert cli.main(["migrate", "--worker"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result == {"error": "migrate:CommandError"}

    monkeypatch.setattr(Startup, "git_commit", staticmethod(lambda: "test"))
    startup = Startup({"runtime": "colab"})
    startup.completed = 6
    startup.report["expected_head"] = repository_head(isolated_database)
    from src.ops import subprocesses
    monkeypatch.setattr(subprocesses, "run_bounded", lambda *_args, **_kwargs: SimpleNamespace(
        returncode=1, stdout="error=migrate:CommandError\n"
    ))
    with pytest.raises(Blocker, match="migrate failed: migrate:CommandError"):
        startup.run(7)
    assert startup.report["SYSTEM_READY"] == "NO"
