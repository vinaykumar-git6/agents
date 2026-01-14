"""
Legacy utilities for backward compatibility.
Provides setup_logger function used by older agent modules.
"""

import logging
from .logging_config import get_logger


def setup_logger(name: str) -> logging.Logger:
    """
    Set up and return a logger instance.
    
    This is a legacy wrapper around get_logger for backward compatibility.
    
    Args:
        name: Logger name (typically __name__)
    
    Returns:
        Logger instance
    """
    return get_logger(name)
