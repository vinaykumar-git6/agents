"""
Retry handler with exponential backoff for Azure API calls.
"""

import time
import logging
import functools
from typing import Callable, Any, TypeVar, cast

from azure.core.exceptions import (
    HttpResponseError,
    ServiceRequestError,
    ServiceResponseError
)

from architecture_diagram_agents.core.exceptions import AgentTimeoutError


logger = logging.getLogger(__name__)

T = TypeVar('T')


def is_transient_error(exception: Exception) -> bool:
    """
    Determine if an exception is transient and retry-able.
    
    Args:
        exception: Exception to check
    
    Returns:
        True if exception is transient
    """
    if isinstance(exception, HttpResponseError):
        # Retry on throttling, server errors, timeouts
        return exception.status_code in [429, 500, 502, 503, 504]
    
    if isinstance(exception, (ServiceRequestError, ServiceResponseError)):
        return True
    
    return False


def retry_with_exponential_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0
) -> Callable:
    """
    Decorator to retry function calls with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay between retries
        exponential_base: Base for exponential backoff calculation
    
    Returns:
        Decorated function with retry logic
    
    Example:
        @retry_with_exponential_backoff(max_retries=3, initial_delay=1.0)
        async def call_api():
            return await client.analyze()
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            delay = initial_delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt == max_retries:
                        logger.error(
                            f"{func.__name__} failed after {max_retries} retries: {str(e)}"
                        )
                        raise
                    
                    if not is_transient_error(e):
                        logger.warning(
                            f"{func.__name__} failed with non-transient error: {str(e)}"
                        )
                        raise
                    
                    logger.warning(
                        f"{func.__name__} failed (attempt {attempt + 1}/{max_retries}): {str(e)}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    
                    time.sleep(delay)
                    delay = min(delay * exponential_base, max_delay)
            
            # Should not reach here, but just in case
            raise last_exception or AgentTimeoutError("Max retries exceeded")
        
        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            delay = initial_delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt == max_retries:
                        logger.error(
                            f"{func.__name__} failed after {max_retries} retries: {str(e)}"
                        )
                        raise
                    
                    if not is_transient_error(e):
                        logger.warning(
                            f"{func.__name__} failed with non-transient error: {str(e)}"
                        )
                        raise
                    
                    logger.warning(
                        f"{func.__name__} failed (attempt {attempt + 1}/{max_retries}): {str(e)}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    
                    time.sleep(delay)
                    delay = min(delay * exponential_base, max_delay)
            
            # Should not reach here, but just in case
            raise last_exception or AgentTimeoutError("Max retries exceeded")
        
        # Return appropriate wrapper based on function type
        import asyncio
        import inspect
        
        if asyncio.iscoroutinefunction(func):
            return cast(Callable[..., T], async_wrapper)
        else:
            return cast(Callable[..., T], sync_wrapper)
    
    return decorator
