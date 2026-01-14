"""
Input validation utilities.
"""

import os
from typing import Optional
from pathlib import Path

from architecture_diagram_agents.core.exceptions import ValidationError

try:
    from PIL import Image
except ImportError:
    Image = None


# Supported image formats
SUPPORTED_IMAGE_FORMATS = {
    'png', 'jpg', 'jpeg', 'bmp', 'gif', 'tiff', 'webp'
}

# Maximum file size (20 MB)
MAX_FILE_SIZE = 20 * 1024 * 1024


def validate_image_path(image_path: str) -> Path:
    """
    Validate that image path exists and is a valid image file.
    
    Args:
        image_path: Path to image file
    
    Returns:
        Validated Path object
    
    Raises:
        ValidationError: If path is invalid or not an image
    """
    if not image_path:
        raise ValidationError("Image path cannot be empty")
    
    path = Path(image_path)
    
    if not path.exists():
        raise ValidationError(f"Image file does not exist: {image_path}")
    
    if not path.is_file():
        raise ValidationError(f"Path is not a file: {image_path}")
    
    # Check file size
    file_size = path.stat().st_size
    if file_size == 0:
        raise ValidationError(f"Image file is empty: {image_path}")
    
    if file_size > MAX_FILE_SIZE:
        size_mb = file_size / (1024 * 1024)
        raise ValidationError(
            f"Image file too large: {size_mb:.1f}MB (max {MAX_FILE_SIZE / (1024 * 1024)}MB)"
        )
    
    # Check file format using PIL if available
    if Image:
        try:
            with Image.open(path) as img:
                image_format = img.format.lower() if img.format else None
                if not image_format:
                    raise ValidationError(f"Cannot determine image format: {image_path}")
                
                if image_format not in SUPPORTED_IMAGE_FORMATS:
                    raise ValidationError(
                        f"Unsupported image format: {image_format}. "
                        f"Supported formats: {', '.join(SUPPORTED_IMAGE_FORMATS)}"
                    )
        except (IOError, OSError) as e:
            raise ValidationError(f"File is not a valid image: {image_path}. Error: {str(e)}")
    else:
        # Fallback: just check file extension
        ext = path.suffix.lower().lstrip('.')
        if ext not in SUPPORTED_IMAGE_FORMATS:
            raise ValidationError(
                f"Unsupported image format: {ext}. "
                f"Supported formats: {', '.join(SUPPORTED_IMAGE_FORMATS)}"
            )
    
    return path


def validate_url(url: str) -> str:
    """
    Validate that URL is properly formatted.
    
    Args:
        url: URL to validate
    
    Returns:
        Validated URL string
    
    Raises:
        ValidationError: If URL is invalid
    """
    if not url:
        raise ValidationError("URL cannot be empty")
    
    url = url.strip()
    
    if not url.startswith(('http://', 'https://')):
        raise ValidationError("URL must start with http:// or https://")
    
    if len(url) > 2048:
        raise ValidationError("URL too long (max 2048 characters)")
    
    return url


def validate_endpoint(endpoint: str) -> str:
    """
    Validate Azure Computer Vision endpoint.
    
    Args:
        endpoint: Endpoint URL
    
    Returns:
        Validated endpoint
    
    Raises:
        ValidationError: If endpoint is invalid
    """
    if not endpoint:
        raise ValidationError("Azure Computer Vision endpoint is required")
    
    endpoint = endpoint.strip()
    
    if not endpoint.startswith('https://'):
        raise ValidationError("Endpoint must use HTTPS")
    
    if not endpoint.endswith('cognitiveservices.azure.com/'):
        if not endpoint.endswith('cognitiveservices.azure.com'):
            raise ValidationError("Invalid Azure Cognitive Services endpoint format")
        endpoint = endpoint + '/'
    
    return endpoint


def validate_config_value(
    value: Optional[str],
    name: str,
    required: bool = True,
    min_length: Optional[int] = None,
    max_length: Optional[int] = None
) -> Optional[str]:
    """
    Validate configuration value.
    
    Args:
        value: Configuration value
        name: Name of configuration parameter
        required: Whether value is required
        min_length: Minimum length if specified
        max_length: Maximum length if specified
    
    Returns:
        Validated value
    
    Raises:
        ValidationError: If validation fails
    """
    if not value:
        if required:
            raise ValidationError(f"{name} is required")
        return None
    
    value = value.strip()
    
    if min_length and len(value) < min_length:
        raise ValidationError(f"{name} must be at least {min_length} characters")
    
    if max_length and len(value) > max_length:
        raise ValidationError(f"{name} must be at most {max_length} characters")
    
    return value


def validate_positive_number(
    value: Optional[float],
    name: str,
    required: bool = True,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None
) -> Optional[float]:
    """
    Validate positive numeric configuration value.
    
    Args:
        value: Numeric value
        name: Name of parameter
        required: Whether value is required
        min_value: Minimum allowed value
        max_value: Maximum allowed value
    
    Returns:
        Validated value
    
    Raises:
        ValidationError: If validation fails
    """
    if value is None:
        if required:
            raise ValidationError(f"{name} is required")
        return None
    
    if value <= 0:
        raise ValidationError(f"{name} must be positive")
    
    if min_value is not None and value < min_value:
        raise ValidationError(f"{name} must be at least {min_value}")
    
    if max_value is not None and value > max_value:
        raise ValidationError(f"{name} must be at most {max_value}")
    
    return value
