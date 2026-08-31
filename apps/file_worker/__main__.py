"""python -m apps.file_worker — parse session attachments (shared uploads volume)."""

from apps.file_worker.worker import run_forever

if __name__ == "__main__":
    run_forever()
