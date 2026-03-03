"""Базовая настройка логирования сервиса."""

from __future__ import annotations

import logging


def setup_logging(level: int = logging.INFO) -> None:
    """Настраивает root-логгер для локального и контейнерного запуска."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
