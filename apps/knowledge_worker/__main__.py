"""python -m apps.knowledge_worker — async RAG PDF ingest (shared uploads volume)."""

from apps.knowledge_worker.worker import run_forever

if __name__ == "__main__":
    run_forever()
