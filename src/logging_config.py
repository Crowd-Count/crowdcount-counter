#!/usr/bin/env python3
"""
Logging Configuration for CrowdCount Counter
Provides file and console logging with rotation for production debugging
"""

import logging
import logging.handlers
import os
from pathlib import Path


def setup_logging(name: str, log_dir: str = None, level: int = logging.INFO) -> logging.Logger:
    """
    Setup logging with both console and file output.

    Args:
        name: Logger name (typically __name__ of calling module)
        log_dir: Directory for log files (default: /var/log/crowdcount or ~/.local/log/crowdcount)
        level: Logging level (default: INFO)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger

    logger.setLevel(level)

    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console handler - always add
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler - try to create if possible
    if log_dir is None:
        # Try system log directory first, then user directory
        if os.path.exists('/var/log') and os.access('/var/log', os.W_OK):
            log_dir = '/var/log/crowdcount'
        else:
            log_dir = str(Path.home() / '.local' / 'log' / 'crowdcount')

    try:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        log_file = Path(log_dir) / f'{name.replace(".", "_")}.log'

        # Rotating file handler - 5MB max, keep 3 backups
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=3,
            encoding='utf-8'
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    except (PermissionError, OSError) as e:
        # Can't create file handler, continue with console only
        logger.warning(f"Could not setup file logging: {e}")

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Get or create a logger with default configuration.

    Args:
        name: Logger name

    Returns:
        Logger instance
    """
    logger = logging.getLogger(name)

    # If logger has no handlers, set it up with defaults
    if not logger.handlers:
        return setup_logging(name)

    return logger
