"""
Configuration management for Architecture Diagram Analyzer.

Handles environment variables, Azure authentication, and application settings.
"""

import os
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from pathlib import Path

from azure.identity import DefaultAzureCredential, AzureCliCredential, ManagedIdentityCredential
from azure.core.credentials import TokenCredential

from .exceptions import ConfigurationError


@dataclass
class Config:
    """
    Application configuration with Azure settings.
    
    Loads configuration from environment variables with sensible defaults.
    """
    
    # Azure Computer Vision
    computer_vision_endpoint: str = ""
    computer_vision_api_version: str = "2023-04-01-preview"
    
    # Microsoft Foundry (formerly Azure AI Foundry)
    ai_project_endpoint: str = ""
    ai_model_deployment_name: str = "gpt-4o-mini"
    
    # Authentication
    credential_type: str = "cli"  # cli, managed_identity, default
    use_managed_identity: bool = False
    tenant_id: Optional[str] = None
    
    # Application Settings
    flask_env: str = "development"
    flask_debug: bool = True
    flask_host: str = "0.0.0.0"
    flask_port: int = 5000
    max_upload_size_mb: int = 16
    default_region: str = "uaenorth"
    
    # Retry and Timeout
    max_retries: int = 3
    retry_delay: float = 1.0
    max_retry_delay: float = 10.0
    request_timeout: int = 30
    
    # Logging
    log_level: str = "INFO"
    log_format: str = "text"
    log_to_file: bool = False
    log_file_path: str = "logs/app.log"
    
    # Agent Configuration
    enable_ai_agent: bool = True
    enable_keyword_fallback: bool = True
    agent_timeout: int = 60
    
    # Feature Flags
    enable_caching: bool = False
    cache_ttl: int = 3600
    enable_telemetry: bool = False
    
    # Security
    allowed_extensions: str = "png,jpg,jpeg,gif,bmp"
    enable_cors: bool = False
    cors_origins: str = ""
    
    # Internal
    _credential: Optional[TokenCredential] = field(default=None, init=False, repr=False)
    
    @classmethod
    def from_environment(cls) -> "Config":
        """
        Create configuration from environment variables.
        
        Returns:
            Config instance populated from environment
        """
        return cls(
            # Azure Computer Vision
            computer_vision_endpoint=os.getenv("AZURE_COMPUTER_VISION_ENDPOINT", ""),
            computer_vision_api_version=os.getenv("AZURE_COMPUTER_VISION_API_VERSION", "2023-04-01-preview"),
            
            # Microsoft Foundry
            ai_project_endpoint=os.getenv("AZURE_AI_PROJECT_ENDPOINT", ""),
            ai_model_deployment_name=os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4o-mini"),
            
            # Authentication
            credential_type=os.getenv("AZURE_CREDENTIAL_TYPE", "cli").lower(),
            use_managed_identity=os.getenv("AZURE_USE_MANAGED_IDENTITY", "false").lower() == "true",
            tenant_id=os.getenv("AZURE_TENANT_ID"),
            
            # Application
            flask_env=os.getenv("FLASK_ENV", "development"),
            flask_debug=os.getenv("FLASK_DEBUG", "true").lower() == "true",
            flask_host=os.getenv("FLASK_HOST", "0.0.0.0"),
            flask_port=int(os.getenv("FLASK_PORT", "5000")),
            max_upload_size_mb=int(os.getenv("MAX_UPLOAD_SIZE_MB", "16")),
            default_region=os.getenv("DEFAULT_REGION", "uaenorth"),
            
            # Retry and Timeout
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            retry_delay=float(os.getenv("RETRY_DELAY", "1.0")),
            max_retry_delay=float(os.getenv("MAX_RETRY_DELAY", "10.0")),
            request_timeout=int(os.getenv("REQUEST_TIMEOUT", "30")),
            
            # Logging
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_format=os.getenv("LOG_FORMAT", "text"),
            log_to_file=os.getenv("LOG_TO_FILE", "false").lower() == "true",
            log_file_path=os.getenv("LOG_FILE_PATH", "logs/app.log"),
            
            # Agent
            enable_ai_agent=os.getenv("ENABLE_AI_AGENT", "true").lower() == "true",
            enable_keyword_fallback=os.getenv("ENABLE_KEYWORD_FALLBACK", "true").lower() == "true",
            agent_timeout=int(os.getenv("AGENT_TIMEOUT", "60")),
            
            # Features
            enable_caching=os.getenv("ENABLE_CACHING", "false").lower() == "true",
            cache_ttl=int(os.getenv("CACHE_TTL", "3600")),
            enable_telemetry=os.getenv("ENABLE_TELEMETRY", "false").lower() == "true",
            
            # Security
            allowed_extensions=os.getenv("ALLOWED_EXTENSIONS", "png,jpg,jpeg,gif,bmp"),
            enable_cors=os.getenv("ENABLE_CORS", "false").lower() == "true",
            cors_origins=os.getenv("CORS_ORIGINS", "")
        )
    
    def validate(self) -> None:
        """
        Validate configuration values.
        
        Raises:
            ConfigurationError: If configuration is invalid
        """
        if not self.computer_vision_endpoint:
            raise ConfigurationError("AZURE_COMPUTER_VISION_ENDPOINT is required")
        
        if not self.computer_vision_endpoint.startswith("https://"):
            raise ConfigurationError("AZURE_COMPUTER_VISION_ENDPOINT must be HTTPS")
        
        if self.enable_ai_agent and not self.ai_project_endpoint:
            raise ConfigurationError(
                "AZURE_AI_PROJECT_ENDPOINT is required when AI agent is enabled"
            )
        
        if self.max_retries < 0:
            raise ConfigurationError("MAX_RETRIES must be non-negative")
        
        if self.retry_delay <= 0:
            raise ConfigurationError("RETRY_DELAY must be positive")
        
        if self.max_upload_size_mb <= 0:
            raise ConfigurationError("MAX_UPLOAD_SIZE_MB must be positive")
    
    def get_credential(self) -> TokenCredential:
        """
        Get Azure credential based on configuration.
        
        Returns:
            Azure credential instance
        
        Raises:
            ConfigurationError: If credential type is unsupported
        """
        if self._credential:
            return self._credential
        
        if self.credential_type == "cli":
            self._credential = AzureCliCredential()
        elif self.credential_type == "managed_identity":
            self._credential = ManagedIdentityCredential()
        elif self.credential_type == "default":
            self._credential = DefaultAzureCredential()
        else:
            raise ConfigurationError(
                f"Unsupported credential type: {self.credential_type}. "
                "Use 'cli', 'managed_identity', or 'default'"
            )
        
        return self._credential
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary (excluding sensitive data)."""
        return {
            "computer_vision_endpoint": self.computer_vision_endpoint,
            "ai_project_endpoint": self.ai_project_endpoint,
            "ai_model_deployment_name": self.ai_model_deployment_name,
            "credential_type": self.credential_type,
            "default_region": self.default_region,
            "max_retries": self.max_retries,
            "enable_ai_agent": self.enable_ai_agent,
            "flask_env": self.flask_env
        }
    
    def get_allowed_extensions(self) -> set:
        """Get set of allowed file extensions."""
        return set(ext.strip().lower() for ext in self.allowed_extensions.split(","))
