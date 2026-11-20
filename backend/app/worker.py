"""Standalone background worker: ``python -m app.worker``.

Use this when the API runs with EMBEDDED_WORKER=false (e.g. a separate Render background worker service).
"""

from __future__ import annotations

import logging
import signal
import threading

from app.core.config import get_settings
from app.services.jobs import worker_loop


def main() -> None:
    logging.basicConfig(level=get_settings().log_level.upper(), format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    worker_loop(stop)


if __name__ == "__main__":
    main()
