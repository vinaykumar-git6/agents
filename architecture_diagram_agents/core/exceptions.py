"""
Custom exceptions for the Architecture Diagram Analyzer.
"""


class AnalyzerError(Exception):
    """Base exception for all analyzer errors."""
    pass


class ConfigurationError(AnalyzerError):
    """Raised when configuration is invalid or missing."""
    pass


class VisionAnalysisError(AnalyzerError):
    """Raised when Computer Vision analysis fails."""
    pass


class AgentError(AnalyzerError):
    """Raised when agent execution fails."""
    pass


class AgentInitializationError(AgentError):
    """Raised when agent initialization fails."""
    pass


class AgentTimeoutError(AgentError):
    """Raised when agent execution times out."""
    pass


class OrchestrationError(AnalyzerError):
    """Raised when agent orchestration fails."""
    pass


class ValidationError(AnalyzerError):
    """Raised when input validation fails."""
    pass


class AuthenticationError(AnalyzerError):
    """Raised when Azure authentication fails."""
    pass


class ResourceNotFoundError(AnalyzerError):
    """Raised when required Azure resource is not found."""
    pass
