# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Application logging without changing the embedding application's root logger."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOGGER_NAME = "vic3_state_merger"
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_owned_handlers: list[logging.Handler] = []


class EncodingSafeStreamHandler(logging.StreamHandler):
    """Escape characters a console cannot represent, including in tracebacks."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record) + self.terminator
            encoding = getattr(self.stream, "encoding", None)
            if encoding:
                message = message.encode(encoding, errors="backslashreplace").decode(
                    encoding
                )
            self.stream.write(message)
            self.flush()
        except RecursionError:
            raise
        except Exception:  # noqa: BLE001 - Match StreamHandler's error boundary.
            self.handleError(record)


def configure_logging(
    level: str = "INFO", *, log_file: str | Path | None = None, console: bool = True
) -> None:
    """Replace only handlers owned by this application; files rotate in UTF-8.

    File setup happens before replacing existing handlers, so an unavailable log
    destination leaves the previous configuration intact and raises to the caller.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    handlers: list[logging.Handler] = []
    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                path,
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
                errors="backslashreplace",
            )
        )
    if console and sys.stderr is not None:
        handlers.append(EncodingSafeStreamHandler(sys.stderr))
    for handler in handlers:
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(_FORMAT))
    for handler in _owned_handlers:
        logger.removeHandler(handler)
        handler.close()
    _owned_handlers[:] = handlers
    for handler in handlers:
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
