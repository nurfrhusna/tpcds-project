FROM python:3.12-slim-bookworm
RUN pip install --no-cache-dir duckdb==1.4.1
WORKDIR /app
COPY validation/worker.py validation/sql_dialect.py validation/schema.json ./
COPY validation/canonical-queries ./canonical-queries
COPY validation_helpers.py ./
COPY project-snapshot/scripts/bulk_import.py ./original_importer.py
COPY project-snapshot/queries ./queries
ENTRYPOINT ["python", "/app/worker.py"]
