# Minimal image for running AI-generated pytest tests. Built once; run with --network none, read-only mounts.
FROM python:3.12-slim
RUN pip install --no-cache-dir pytest coverage
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /tmp
