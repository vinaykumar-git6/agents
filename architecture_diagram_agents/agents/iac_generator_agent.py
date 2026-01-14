"""
IAC Generator Agent using Microsoft Agent Framework with Azure AI Foundry.
Generates Terraform Infrastructure as Code based on analyzed Azure services.
"""

import os
import asyncio
from typing import Optional

from azure.identity import AzureCliCredential
from agent_framework import ChatAgent
from agent_framework.azure import AzureAIAgentClient
from dotenv import load_dotenv

from ..core.config import Config
from ..utils.legacy_utils import setup_logger
from ..utils.logging_config import setup_logging

# Load .env from project root
env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=env_path, override=True)

# Initialize logging
setup_logging(level="INFO")

logger = setup_logger(__name__)

# Configuration
project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
model_deployment_name = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4o-mini")


class IACGeneratorAgent:
    """
    Agent that generates Terraform Infrastructure as Code based on analyzed Azure services.
    Uses Microsoft Agent Framework for intelligent code generation.
    """
    
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config.from_environment()
        self.project_endpoint = project_endpoint
        self.model_deployment_name = model_deployment_name
        self.agent: Optional[ChatAgent] = None
        self._initialized = False
        logger.info("IACGeneratorAgent instantiated")
    
    async def initialize(self) -> None:
        """Initialize Azure AI agent for IAC generation."""
        if self._initialized:
            return
        
        try:
            credential = AzureCliCredential()
            client = AzureAIAgentClient(
                project_endpoint=self.project_endpoint,
                model_deployment_name=self.model_deployment_name,
                credential=credential
            )
            
            # Check if model supports store feature (GPT models only, not Grok/DeepSeek)
            model_lower = self.model_deployment_name.lower()
            supports_store = any(m in model_lower for m in ["gpt-4", "gpt-35", "gpt4", "gpt35"])
            
            logger.info(f"Initializing IACGeneratorAgent with model: {self.model_deployment_name} (store={supports_store})")
            
            # Create IAC generator agent with instructions
            self.agent = client.create_agent(
                name="TerraformGenerator",
                instructions="""You are an expert Azure Infrastructure as Code (IaC) architect specializing in Terraform.

Your task is to generate production-ready Terraform code for Azure services following these MANDATORY requirements:

**Required Files:**
1. providers.tf - Terraform and Azure provider configuration with version constraints
2. main.tf - All resource definitions with proper dependencies, naming, and COMPREHENSIVE COMMENTS
3. variables.tf - All input variables with types, descriptions, and validation rules
4. outputs.tf - All output values with descriptions
5. terraform.tfvars - Example variable values ready for deployment
6. README.md - Complete deployment guide with prerequisites, setup steps, and usage instructions

**Code Quality Standards:**
✓ Add detailed comments above EVERY resource explaining its purpose
✓ Use Azure naming conventions (e.g., rg-, app-, kv-, st-, etc.)
✓ Include proper resource tags (Environment, ManagedBy, Application)
✓ Define resource dependencies explicitly using depends_on when needed
✓ Use variables for ALL configurable values (no hardcoded values)
✓ Include validation blocks for critical variables
✓ Follow Azure security best practices (managed identities, Key Vault references, etc.)
✓ Add helpful descriptions to all variables and outputs

**README.md Must Include:**
- Overview of the infrastructure being created
- Prerequisites (Azure CLI, Terraform version, required permissions)
- Step-by-step deployment instructions
- Configuration variables explanation
- Post-deployment verification steps
- Clean-up/destroy instructions

Generate each file with clear section headers:
=== providers.tf ===
=== main.tf ===
=== variables.tf ===
=== outputs.tf ===
=== terraform.tfvars ===
=== README.md ===

IMPORTANT: Every resource in main.tf MUST have a comment block explaining what it does and why it's needed.""",
                store=supports_store
            )
            
            self._initialized = True
            logger.info("IACGeneratorAgent initialized successfully with ChatAgent")
            
        except Exception as e:
            logger.error(f"Failed to initialize IACGeneratorAgent: {e}")
            raise
    
    async def close(self) -> None:
        """Close the agent connection."""
        try:
            if self.agent:
                logger.info("Closing IACGeneratorAgent")
        except Exception as e:
            logger.warning(f"Error closing agent: {e}")


async def main():
    """Test the IAC Generator Agent."""
    try:
        agent = IACGeneratorAgent()
        await agent.initialize()
        logger.info("IACGeneratorAgent ready for use")
        
    except Exception as e:
        logger.error(f"Failed to initialize IACGeneratorAgent: {e}")
        return None


if __name__ == "__main__":
    asyncio.run(main())
