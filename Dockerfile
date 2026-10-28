# INViSU Preservation Reader — Hugging Face Docker Space (port 7860)
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd -m -u 1000 user && chown -R user /app
USER user

# the ledger must be writable in the container; the index and pages are read-only
ENV PYTHONUNBUFFERED=1 \
    TF_LEDGER=/tmp/cost_ledger.jsonl \
    RENDITION_CACHE=/tmp \
    PROJECT_DIR=/app/data/iolani-palace

EXPOSE 7860
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "7860"]
