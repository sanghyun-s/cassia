# CASSIA — Accounting AI Chatbot (FastAPI + LangChain + ChromaDB + OpenAI)
# -----------------------------------------------------------------------------
# Pure-Python service (no Node CLI needed — unlike the sibling PREPARE app).
#
# Seed data:
#   * accounting.db  — built at image-build time from data/*.csv (no API key).
#   * chroma_db      — vector store from data/*.pdf. Embedding needs
#                      OPENAI_API_KEY. If you pass it as a build arg it is baked
#                      into the image (fast cold starts, embedded once per
#                      deploy). If not, the app builds it on first boot instead
#                      (see _ensure_seed_data in backend/main.py).
#
# Bake the vector store at build time (recommended) with:
#   docker build --build-arg OPENAI_API_KEY=sk-... -t cassia .
# On Render, set OPENAI_API_KEY as a build-time env var to get the same effect.

FROM python:3.12-slim

# Needed by some wheels (chromadb/onnxruntime) at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Python dependencies (cached layer) --------------------------------------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- App code + committed source data ----------------------------------------
COPY . .

# --- Build seed data ---------------------------------------------------------
# accounting.db: deterministic, no API key required.
RUN python sql/phase1_load.py

# chroma_db: embed the PDFs only if a build-time key is supplied; otherwise the
# runtime fallback builds it on first boot.
ARG OPENAI_API_KEY=""
RUN if [ -n "$OPENAI_API_KEY" ]; then \
        echo "Baking chroma_db at build time..." && \
        OPENAI_API_KEY="$OPENAI_API_KEY" python rag/phase1_ingest.py ; \
    else \
        echo "No build-arg OPENAI_API_KEY — chroma_db will build on first boot." ; \
    fi

# Most PaaS inject $PORT; default to 8002 for local `docker run`.
ENV PORT=8002
EXPOSE 8002

# main.py lives in backend/ and imports sibling modules by name, so run from
# there. Shell form expands $PORT at runtime.
CMD cd backend && uvicorn main:app --host 0.0.0.0 --port ${PORT}
