"""
Configuration management for Architecture Diagram to IaC Agents project.

Uses Pydantic settings to load and validate environment variables.
Supports Azure managed identity authentication (preferred) and key-based auth.
"""

from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AzureAIConfig(BaseSettings):
    """Azure AI Foundry configuration for agent creation."""

    project_endpoint: str = Field(
        ...,
        description="Azure AI Foundry project endpoint",
        alias="AZURE_AI_PROJECT_ENDPOINT",
    )
    model_deployment_name: str = Field(
        default="gpt-4o",
        description="Model deployment name in Azure AI Foundry",
        alias="AZURE_AI_MODEL_DEPLOYMENT_NAME",
    )
    api_key: Optional[str] = Field(
        default=None,
        description="API key (optional, uses DefaultAzureCredential if not provided)",
        alias="AZURE_AI_API_KEY",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


class ComputerVisionConfig(BaseSettings):
    """Azure Computer Vision service configuration."""

    endpoint: str = Field(
        ...,
        description="Azure Computer Vision endpoint",
        alias="AZURE_COMPUTER_VISION_ENDPOINT",
    )
    key: Optional[str] = Field(
        default=None,
        description="API key (optional, uses DefaultAzureCredential if not provided)",
        alias="AZURE_COMPUTER_VISION_KEY",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, v: str) -> str:
        """Ensure endpoint ends with /"""
        return v if v.endswith("/") else f"{v}/"


class AzureDeploymentConfig(BaseSettings):
    """Azure subscription and deployment configuration."""

    subscription_id: str = Field(
        ...,
        description="Azure subscription ID for deployments",
        alias="AZURE_SUBSCRIPTION_ID",
    )
    resource_group: str = Field(
        default="rg-archdiag-iac",
        description="Default resource group for deployments",
        alias="AZURE_RESOURCE_GROUP",
    )
    location: str = Field(
        default="eastus",
        description="Default Azure region for resources",
        alias="AZURE_LOCATION",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


class APIConfig(BaseSettings):
    """API server configuration."""

    host: str = Field(
        default="0.0.0.0",
        description="API server host",
        alias="API_HOST",
    )
    port: int = Field(
        default=8000,
        description="API server port",
        alias="API_PORT",
    )
    max_upload_size_mb: int = Field(
        default=10,
        description="Maximum upload size in MB",
        alias="MAX_UPLOAD_SIZE_MB",
    )
    allowed_image_extensions: list[str] = Field(
        default=[".png", ".jpg", ".jpeg", ".bmp", ".tiff"],
        description="Allowed image file extensions",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("allowed_image_extensions", mode="before")
    @classmethod
    def parse_extensions(cls, v) -> list[str]:
        """Parse comma-separated extensions from env var."""
        if isinstance(v, str):
            return [ext.strip() for ext in v.split(",")]
        return v


class WorkflowConfig(BaseSettings):
    """Workflow behavior configuration."""

    enable_auto_deploy: bool = Field(
        default=False,
        description="Enable automatic deployment without manual approval",
        alias="ENABLE_AUTO_DEPLOY",
    )
    require_review_approval: bool = Field(
        default=True,
        description="Require human approval after IaC review",
        alias="REQUIRE_REVIEW_APPROVAL",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


class MonitoringConfig(BaseSettings):
    """Application monitoring and logging configuration."""

    connection_string: Optional[str] = Field(
        default=None,
        description="Application Insights connection string",
        alias="APPLICATIONINSIGHTS_CONNECTION_STRING",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level",
        alias="LOG_LEVEL",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        allowed = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in allowed:
            raise ValueError(f"Log level must be one of {allowed}")
        return v_upper


class Settings(BaseSettings):
    """Main settings class aggregating all configuration sections."""

    azure_ai: AzureAIConfig = Field(default_factory=AzureAIConfig)
    computer_vision: ComputerVisionConfig = Field(default_factory=ComputerVisionConfig)
    azure_deployment: AzureDeploymentConfig = Field(default_factory=AzureDeploymentConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get the global settings instance."""
    return settings
