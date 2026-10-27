"""Trusted entry point mounted into the bubblewrap backend namespace."""

import json
import logging
import resource
import sys
import traceback


class CorrelatedFormatter(logging.Formatter):
    """Retain actual backend exception and request correlation as bounded JSONL."""

    def format(self, record: logging.LogRecord) -> str:
        event = {
            "message": record.getMessage(),
            "case_id": getattr(record, "case_id", None),
            "request_id": getattr(record, "request_id", None),
            "route": getattr(record, "route", None),
            "exception_type": getattr(record, "exception_type", None),
        }
        if record.exc_info:
            event["traceback"] = "".join(traceback.format_exception(*record.exc_info))[-16384:]
        return json.dumps(event)


def main() -> None:
    """Apply resource bounds before importing any candidate application module."""
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (40, 40))
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    sys.path[:0] = ["/packages", "/snapshot/apps/buggyshop-backend"]
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(CorrelatedFormatter())
    logger = logging.getLogger("buggyshop.api")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    import uvicorn

    uvicorn.run(
        "app.main:app",
        fd=int(sys.argv[1]),
        log_level="warning",
        access_log=False,
        log_config=None,
        lifespan="off",
        workers=1,
    )


if __name__ == "__main__":
    main()
