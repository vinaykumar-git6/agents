"""
Configuration management for the Incident Management Agents.
Loads environment variables and provides configuration settings.
"""
import os
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=env_path, override=True)


class AzureAIConfig(BaseSettings):
    """Azure AI Foundry configuration."""
    project_endpoint: str = Field(alias="AZURE_AI_PROJECT_ENDPOINT")
    model_deployment_name: str = Field(alias="AZURE_AI_MODEL_DEPLOYMENT_NAME")


class CosmosDBConfig(BaseSettings):
    """Azure Cosmos DB configuration."""
    endpoint: str = Field(alias="COSMOS_ENDPOINT")
    database_name: str = Field(alias="COSMOS_DATABASE_NAME")
    incidents_container: str = Field(alias="COSMOS_INCIDENTS_CONTAINER")
    workflow_state_container: str = Field(alias="COSMOS_WORKFLOW_STATE_CONTAINER")
    approvals_container: str = Field(alias="COSMOS_APPROVALS_CONTAINER")


class AzureSearchConfig(BaseSettings):
    """Azure AI Search configuration."""
    endpoint: str = Field(alias="AZURE_SEARCH_ENDPOINT")
    index_name: str = Field(alias="AZURE_SEARCH_INDEX_NAME")


class CommunicationConfig(BaseSettings):
    """Azure Communication Services configuration."""
    connection_string: str = Field(alias="AZURE_COMMUNICATION_CONNECTION_STRING")
    sender_email: str = Field(alias="AZURE_COMMUNICATION_SENDER_EMAIL")


class ServiceNowConfig(BaseSettings):
    """ServiceNow integration configuration."""
    instance_url: str = Field(alias="SERVICENOW_INSTANCE_URL")
    api_user: str = Field(alias="SERVICENOW_API_USER")
    api_password: str = Field(alias="SERVICENOW_API_PASSWORD")


class AzureFunctionsConfig(BaseSettings):
    """Azure Functions configuration."""
    remediation_url: str = Field(alias="AZURE_FUNCTIONS_REMEDIATION_URL")
    function_key: Optional[str] = Field(default=None, alias="AZURE_FUNCTIONS_KEY")


class ApprovalConfig(BaseSettings):
    """Human-in-the-loop approval configuration."""
    required_emails: list[str] = Field(alias="APPROVAL_REQUIRED_EMAILS")
    timeout_minutes: int = Field(default=30, alias="APPROVAL_TIMEOUT_MINUTES")

    class Config:
        @staticmethod
        def parse_env_var(field_name: str, raw_val: str) -> list[str]:
            if field_name == "required_emails":
                return [email.strip() for email in raw_val.split(",")]
            return raw_val


class MonitoringConfig(BaseSettings):
    """Application Insights monitoring configuration."""
    connection_string: Optional[str] = Field(
        default=None, alias="APPLICATIONINSIGHTS_CONNECTION_STRING"
    )


class WebhookConfig(BaseSettings):
    """Webhook server configuration."""
    host: str = Field(default="0.0.0.0", alias="WEBHOOK_SERVER_HOST")
    port: int = Field(default=8000, alias="WEBHOOK_SERVER_PORT")
    secret_token: str = Field(alias="WEBHOOK_SECRET_TOKEN")


class WorkflowConfig(BaseSettings):
    """Workflow execution configuration."""
    max_retry_attempts: int = Field(default=3, alias="MAX_RETRY_ATTEMPTS")
    retry_base_delay_seconds: float = Field(default=2.0, alias="RETRY_BASE_DELAY_SECONDS")


class Config:
    """Main configuration class that aggregates all configuration sections."""
    
    def __init__(self):
        self.azure_ai = AzureAIConfig()
        self.cosmos_db = CosmosDBConfig()
        self.azure_search = AzureSearchConfig()
        self.communication = CommunicationConfig()
        self.servicenow = ServiceNowConfig()
        self.azure_functions = AzureFunctionsConfig()
        self.approval = ApprovalConfig()
        self.monitoring = MonitoringConfig()
        self.webhook = WebhookConfig()
        self.workflow = WorkflowConfig()


# Global configuration instance
config = Config()
