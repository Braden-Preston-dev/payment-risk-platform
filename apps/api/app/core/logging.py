import json
import logging
from datetime import UTC, datetime
from typing import Any


_STANDARD_FIELDS = set(logging.makeLogRecord({}).__dict__)


class JsonFormatter(logging.Formatter):
    def __init__(self, default_service: str) -> None:
        super().__init__()
        self.default_service = default_service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "service": getattr(record, "service", self.default_service),
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_FIELDS and key not in {"message", "asctime"}:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(service: str = "api") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
