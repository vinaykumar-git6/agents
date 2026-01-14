"""
Centralized logging configuration with date-wise log file rotation.
"""

import logging
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional


def setup_logging(
    level: str = "INFO",
    log_format: Optional[str] = None,
    log_to_file: bool = True
) -> None:
    """
    Configure application-wide logging with date-wise file rotation.
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: Custom log format string
        log_to_file: Whether to write logs to file (default: True)
    """
    # Default format
    if not log_format:
        log_format = (
            '%(asctime)s - %(name)s - %(levelname)s - '
            '%(filename)s:%(lineno)d - %(message)s'
        )
    
    # Convert level string to logging constant
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    
    # Create formatter
    formatter = logging.Formatter(log_format, datefmt='%Y-%m-%d %H:%M:%S')
    
    # Console handler - only show WARNING and above to keep console clean
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.WARNING)
    
    handlers = [console_handler]
    
    # File handler with date-wise rotation
    if log_to_file:
        # Create logs folder in project root
        logs_dir = Path(__file__).parent.parent.parent / 'logs'
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        # Log file with date suffix (e.g., app_2026-01-08.log)
        log_file = logs_dir / 'app.log'
        
        # TimedRotatingFileHandler rotates at midnight, keeps 30 days of logs
        file_handler = TimedRotatingFileHandler(
            filename=str(log_file),
            when='midnight',
            interval=1,
            backupCount=30,
            encoding='utf-8'
        )
        file_handler.suffix = '%Y-%m-%d'
        file_handler.setFormatter(formatter)
        file_handler.setLevel(numeric_level)
        handlers.append(file_handler)
    
    # Configure root logger
    logging.basicConfig(
        level=numeric_level,
        handlers=handlers,
        force=True
    )
    
    # Set specific loggers to WARNING to reduce noise
    logging.getLogger('azure').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module.
    
    Args:
        name: Logger name (typically __name__)
    
    Returns:
        Logger instance
    """
    return logging.getLogger(name)
