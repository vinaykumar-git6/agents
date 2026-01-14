"""
Core package for shared models, configuration, and exceptions.
"""

from .config import Config
from .models import (
    CloudProvider,
    ServiceCategory,
    BoundingBox,
    ImageCaption,
    ImageTag,
    DetectedObject,
    ExtractedText,
    VisionAnalysisResult,
    AzureService,
    AgentAnalysisResult,
    AnalysisResult
)
from .exceptions import (
    AnalyzerError,
    VisionAnalysisError,
    AgentError,
    AgentInitializationError,
    AgentTimeoutError,
    OrchestrationError,
    ValidationError,
    ConfigurationError,
    AuthenticationError,
    ResourceNotFoundError
)

__all__ = [
    'Config',
    'CloudProvider',
    'ServiceCategory',
    'BoundingBox',
    'ImageCaption',
    'ImageTag',
    'DetectedObject',
    'ExtractedText',
    'VisionAnalysisResult',
    'AzureService',
    'AgentAnalysisResult',
    'AnalysisResult',
    'AnalyzerError',
    'VisionAnalysisError',
    'AgentError',
    'AgentInitializationError',
    'AgentTimeoutError',
    'OrchestrationError',
    'ValidationError',
    'ConfigurationError',
    'AuthenticationError',
    'ResourceNotFoundError'
]
