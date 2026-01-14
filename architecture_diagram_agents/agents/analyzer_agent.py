"""
Analyzer Agent using Microsoft Agent Framework with Azure AI Foundry.
Analyzes architecture diagrams to identify Azure services and components.
"""

import os
import asyncio
import json
import re
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


class AnalyzerAgent:
    """
    Agent that analyzes architecture diagrams and identifies Azure services.
    Uses Microsoft Agent Framework to intelligently parse visual elements and extract services.
    """
    
    def __init__(self, config: Optional[Config] = None):
        """
        Initialize the Analyzer Agent.
        
        Args:
            config: Application configuration (optional)
        """
        self.config = config or Config.from_environment()
        self.project_endpoint = project_endpoint
        self.model_deployment_name = model_deployment_name
        self.agent: Optional[ChatAgent] = None
        self._client = None  # Store client reference for cleanup
        self._initialized = False
        logger.info("AnalyzerAgent instantiated")
    
    async def initialize(self) -> None:
        """Initialize Azure AI agent for service analysis."""
        if self._initialized:
            return
        
        try:
            credential = AzureCliCredential()
            self._client = AzureAIAgentClient(
                project_endpoint=self.project_endpoint,
                model_deployment_name=self.model_deployment_name,
                credential=credential
            )
            
            # Create analyzer agent with instructions
            self.agent = self._client.create_agent(
                name="ServiceAnalyzer",
                instructions = """
You are an **Azure Architecture Service Analyzer Agent** with deep expertise in Microsoft Azure cloud services, reference architectures, and solution diagrams.

Your task is to **thoroughly analyze the provided architecture diagram metadata** (including labels, shapes, icons, legends, annotations, connectors, and contextual text) and identify **ALL cloud services and components** with a strong bias toward **Microsoft Azure accuracy and completeness**.

────────────────────────────────────────────
PRIMARY OBJECTIVES
────────────────────────────────────────────
1. Identify **every Azure service explicitly or implicitly represented**
2. Correctly classify each service into **category and subcategory**
3. Infer **service relationships, dependencies, and data flows**
4. Detect the **cloud provider** (Azure / AWS / GCP / Hybrid / Other)
5. Determine or infer the **default Azure region**
6. If non-Azure services are detected, **map them to Azure equivalents**

────────────────────────────────────────────
MANDATORY AZURE SERVICE COVERAGE
────────────────────────────────────────────
You MUST analyze against **ALL Azure service categories**, including but not limited to:

### 1. Compute
- Virtual Machines
- VM Scale Sets
- App Service (Web Apps, API Apps, Function Apps)
- Azure Functions
- Azure Kubernetes Service (AKS)
- Azure Container Apps
- Azure Container Instances
- Azure Batch

### 2. Containers & Images
- Azure Kubernetes Service (AKS)
- Azure Container Registry (ACR)
- Azure Container Apps
- Azure Container Instances
- Docker / OCI artifacts (map to ACR if implied)

### 3. Storage
- Azure Blob Storage
- Azure Data Lake Storage Gen2
- Azure Files
- Azure Queue Storage
- Azure Table Storage
- Managed Disks
- Azure NetApp Files
- Backup Vaults

### 4. Databases & Caching
- Azure SQL Database
- SQL Managed Instance
- Cosmos DB (Core, MongoDB, Cassandra, Table, Gremlin)
- Azure Database for MySQL
- Azure Database for PostgreSQL
- Azure Cache for Redis
- Azure Data Explorer (Kusto)

### 5. Networking
- Virtual Network (VNet)
- Subnets
- Network Security Groups (NSG)
- Azure Load Balancer
- Application Gateway (WAF)
- Azure Front Door
- Azure Firewall
- Private Endpoint / Private Link
- VPN Gateway
- ExpressRoute
- Azure DNS
- Traffic Manager
- NAT Gateway

### 6. Security & Identity
- Microsoft Entra ID (Azure AD)
- Managed Identity
- Azure Key Vault
- Azure Defender for Cloud
- Microsoft Sentinel
- DDoS Protection
- RBAC
- Policy
- Blueprints

### 7. Monitoring, Observability & Operations
- Azure Monitor
- Application Insights
- Log Analytics Workspace
- Managed Grafana
- Workbooks
- Alerts
- Change Tracking
- Update Management

### 8. Integration & Messaging
- Azure Service Bus
- Event Grid
- Event Hubs
- Azure Logic Apps
- Azure API Management
- Azure Functions (integration role)
- Azure Relay

### 9. Data & Analytics
- Azure Data Factory
- Azure Synapse Analytics
- Azure Databricks
- Azure Stream Analytics
- Azure Data Explorer
- Azure Purview / Microsoft Fabric (if implied)

### 10. AI, ML & Search
- Azure OpenAI
- Azure Cognitive Services
- Azure AI Services
- Azure Machine Learning
- Azure AI Search
- Azure Bot Service
- Form Recognizer / Document Intelligence

### 11. DevOps & CI/CD
- Azure DevOps
- Azure Pipelines
- Azure Repos
- Azure Artifacts
- GitHub Actions
- GitHub Enterprise
- Terraform / Bicep (if implied)

### 12. Governance & Management
- Management Groups
- Subscriptions
- Resource Groups
- Azure Policy
- Cost Management
- Azure Advisor
- Azure Arc

────────────────────────────────────────────
ANALYSIS RULES (MANDATORY)
────────────────────────────────────────────
- Analyze **ALL visible and implied elements**
- Normalize service names to **official Azure product names**
- If a service is implied (e.g., "logs", "metrics", "auth", "secrets"), infer the **most likely Azure service**
- Do NOT skip foundational services (VNet, Subnet, Identity, Monitoring)
- Do NOT hallucinate services not supported by diagram evidence
- Prefer **accuracy over brevity**

────────────────────────────────────────────
MULTI-CLOUD HANDLING
────────────────────────────────────────────
If AWS or GCP services are detected:
- Identify original service
- Suggest **closest Azure equivalent**
- Clearly mark as “mapped from non-Azure”

────────────────────────────────────────────
OUTPUT FORMAT (STRICT JSON)
────────────────────────────────────────────
Return JSON ONLY in the following structure:

{
  "cloud_provider": "Microsoft Azure | AWS | GCP | Hybrid | Unknown",
  "default_region": "uaenorth | eastus | westeurope | inferred | unknown",
  "total_services": N,
  "azure_services": [
    {
      "service_name": "Azure Kubernetes Service",
      "category": "Containers",
      "subcategory": "Container Orchestration",
      "description": "Managed Kubernetes service for deploying, scaling, and operating containerized applications with integrated security, networking, and monitoring.",
      "region": "uaenorth",
      "evidence": "AKS icon and label in compute tier",
      "relationships": ["Azure Container Registry", "Azure Monitor"]
    }
  ],
  "data_flows": [
    "Client → Front Door → Application Gateway → AKS → Cosmos DB"
  ],
  "summary": "High-level architectural overview describing workload purpose, patterns, and Azure design choices."
}

────────────────────────────────────────────
QUALITY REQUIREMENTS
────────────────────────────────────────────
- Each service description MUST be **minimum 10 words**
- Categories and subcategories MUST be accurate
- Relationships and data flows MUST be logical
- Output MUST be valid JSON
""",
                store=True
            )
            
            self._initialized = True
            logger.info("AnalyzerAgent initialized successfully with ChatAgent")
            
        except Exception as e:
            logger.error(f"Failed to initialize AnalyzerAgent: {e}")
            raise
    
    async def analyze(self, vision_data: dict) -> dict:
        """
        Analyze vision data to identify Azure services.
        
        Args:
            vision_data: Vision analysis results containing tags, captions, objects, text
        
        Returns:
            Dictionary with identified Azure services and analysis
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            logger.info(f"DEBUG - Analyzer received vision_data: {vision_data}")
            
            # Prepare prompt with vision data
            vision_summary = f"""
Vision Analysis Results:
- Captions: {json.dumps(vision_data.get('dense_captions', [])[:3])}
- Tags: {json.dumps(vision_data.get('tags', [])[:20])}
- Objects: {json.dumps(vision_data.get('objects', [])[:10])}
- Text: {json.dumps(vision_data.get('text', [])[:10])}
- Architecture Type: {vision_data.get('architecture_type', 'unknown')}
- Services Detected: {json.dumps(vision_data.get('services_detected', []))}
"""
            
            prompt = f"""Analyze this architecture diagram data and identify all Azure services:

{vision_summary}

Provide a detailed analysis with all identified Azure services, their categories, and relationships.

Return JSON with comprehensive service descriptions:
{{
  "cloud_provider": "Microsoft Azure",
  "default_region": "uaenorth",
  "total_services": N,
  "azure_services": [
    {{"service_name": "service1", "category": "Compute", "description": "Detailed description of what this service does and its key capabilities"}},
    {{"service_name": "service2", "category": "Storage", "description": "Detailed description of what this service does and its key capabilities"}}
  ],
  "summary": "Summary of the architecture"
}}

Each service description should explain the service's purpose, key features, and role in the architecture."""
            
            logger.info(f"DEBUG - Analyzer sending prompt to ChatAgent: {prompt[:200]}...")
            result = await self.agent.run(prompt)
            
            # Parse result
            response_text = result.text if hasattr(result, 'text') else str(result)
            logger.info(f"DEBUG - Analyzer received response from ChatAgent: {response_text[:500]}...")
            
            # Extract JSON from response
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}[^{}]*)*\}', response_text, re.DOTALL)
            if json_match:
                try:
                    analysis_data = json.loads(json_match.group())
                    logger.info(f"DEBUG - Parsed JSON from response: {analysis_data}")
                except json.JSONDecodeError as e:
                    logger.error(f"DEBUG - JSON parse error: {e}")
                    analysis_data = self._create_default_result()
            else:
                logger.warning("DEBUG - No JSON found in response, using default result")
                analysis_data = self._create_default_result()
            
            # Ensure at least services_detected from vision are included
            if analysis_data.get('total_services', 0) == 0 and vision_data.get('services_detected'):
                logger.info(f"DEBUG - Using vision_detected services: {vision_data.get('services_detected')}")
                analysis_data['azure_services'] = [
                    {'service_name': s, 'category': 'Detected'} 
                    for s in vision_data.get('services_detected', [])
                ]
                analysis_data['total_services'] = len(analysis_data['azure_services'])
            
            logger.info(f"Analysis completed: {analysis_data.get('total_services', 0)} services identified")
            return analysis_data
            
        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            raise
    
    def _create_default_result(self) -> dict:
        """Create a default analysis result structure."""
        return {
            "cloud_provider": "Microsoft Azure",
            "default_region": "uaenorth",
            "total_services": 0,
            "azure_services": [],
            "summary": "Analysis could not be completed"
        }
    
    async def close(self) -> None:
        """Close the agent connection and release resources."""
        try:
            if self._client:
                # Close the underlying HTTP client session
                if hasattr(self._client, '_client') and self._client._client:
                    if hasattr(self._client._client, 'close'):
                        await self._client._client.close()
                elif hasattr(self._client, 'close'):
                    if asyncio.iscoroutinefunction(self._client.close):
                        await self._client.close()
                    else:
                        self._client.close()
            self._initialized = False
            self._client = None
            self.agent = None
            logger.info("AnalyzerAgent closed successfully")
        except Exception as e:
            logger.warning(f"Error closing AnalyzerAgent: {e}")


async def main():
    """Test the Analyzer Agent."""
    try:
        agent = AnalyzerAgent()
        await agent.initialize()
        logger.info("AnalyzerAgent ready for use")
        
    except Exception as e:
        logger.error(f"Failed to initialize AnalyzerAgent: {e}")
        return None


if __name__ == "__main__":
    asyncio.run(main())
