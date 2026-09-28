FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ALEMBIC_CONFIG=/workspace/src/db/alembic.ini
ENV PYTEST_ADDOPTS="-o cache_dir=/tmp/pytest_cache"
WORKDIR /workspace
COPY src/db/requirements.txt src/db/requirements-dev.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements-dev.txt \
    && useradd --create-home dbtools
COPY src/__init__.py src/__init__.py
COPY src/db/ src/db/
COPY tests/test_db.py tests/test_db_postgres.py tests/
USER dbtools
ENTRYPOINT ["python", "-m", "src.db.container_entrypoint"]
CMD ["alembic", "upgrade", "head"]
