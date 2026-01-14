"""
Azure Best Practice Agent - Provides Azure best practices using Agent Framework.
Integrates with Azure AI Search knowledge base AND Microsoft Learn MCP for recommendations.
"""

import asyncio
import os
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from azure.identity.aio import AzureCliCredential
from azure.identity import DefaultAzureCredential
from azure.ai.agents.aio import AgentsClient
from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects import AIProjectClient as SyncAIProjectClient
from azure.ai.projects.models import ConnectionType
from azure.ai.agents.models import (
    ListSortOrder,
    McpTool,
    RequiredMcpToolCall,
    SubmitToolApprovalAction,
    ToolApproval,
)
from agent_framework import ChatAgent
from agent_framework.azure import AzureAIAgentClient
from dotenv import load_dotenv

from ..core.config import Config
from ..utils.legacy_utils import setup_logger
from ..utils.logging_config import setup_logging
from ..utils.pdf_generator import print_best_practices_report, save_best_practices_pdf, PDF_AVAILABLE

# Load .env from project root
env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=env_path, override=True)

# Initialize logging
setup_logging(level="INFO")
logger = setup_logger(__name__)

# Configuration
project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
model_deployment_name = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME")
ai_search_index = os.environ.get("AZURE_SEARCH_INDEX", "rag-1765449557697")

# Microsoft Learn MCP Server
MS_LEARN_MCP_URL = "https://innovationhubapim.azure-api.net/learn/api/mcp"


class AzureBestPracticeAgent:
    """Generates comprehensive Azure best practices recommendations for identified services."""
    
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config.from_environment()
        self.agent: Optional[ChatAgent] = None
        self._initialized = False
        self._credential = None
        self._agents_client = None
        self._created_agent = None
        self._mcp_tool = None  # Microsoft Learn MCP tool
        self._ai_search_conn_id = ""  # Store for later use
        logger.info("AzureBestPracticeAgent instantiated")
    
    async def initialize(self) -> None:
        """Initialize Azure AI agent for best practices with Azure AI Search integration."""
        if self._initialized:
            return
        
        try:
            self._credential = AzureCliCredential()
            await self._credential.__aenter__()
            
            # Get AI Search connection ID
            ai_search_conn_id = ""
            async with AIProjectClient(
                endpoint=project_endpoint,
                credential=self._credential
            ) as project_client:
                async for connection in project_client.connections.list():
                    if connection.type == ConnectionType.AZURE_AI_SEARCH:
                        ai_search_conn_id = connection.id
                        logger.info(f"Found Azure AI Search connection: {ai_search_conn_id}")
                        break
            
            # Use AgentsClient (has create_agent method)
            self._agents_client = AgentsClient(
                endpoint=project_endpoint,
                credential=self._credential
            )
            await self._agents_client.__aenter__()
            
            # Delete existing agent if exists
            agent_name = "BestPracticeAdvisor"
            async for existing_agent in self._agents_client.list_agents():
                if existing_agent.name == agent_name:
                    logger.info(f"Deleting existing agent: {existing_agent.id}")
                    await self._agents_client.delete_agent(existing_agent.id)
                    break
            
            # Store AI Search connection ID for later use
            self._ai_search_conn_id = ai_search_conn_id
            
            # Initialize Microsoft Learn MCP tool
            self._mcp_tool = McpTool(
                server_label="microsoftlearn",
                server_url=MS_LEARN_MCP_URL,
            )
            logger.info(f"Initialized Microsoft Learn MCP tool: {MS_LEARN_MCP_URL}")
            
            # Build tools list - Azure AI Search only (MCP will be added after creation)
            tools_list = []
            if ai_search_conn_id:
                tools_list.append({"type": "azure_ai_search"})
            
            # Build tool resources for AI Search
            tool_resources = {}
            if ai_search_conn_id:
                tool_resources["azure_ai_search"] = {
                    "indexes": [{
                        "index_connection_id": ai_search_conn_id,
                        "index_name": ai_search_index,
                        "query_type": "simple"
                    }]
                }
            
            # Create agent with Azure AI Search tool first
            self._created_agent = await self._agents_client.create_agent(
                model=model_deployment_name,
                name=agent_name,
                instructions="""You are an Azure Well-Architected Framework expert.

CRITICAL REQUIREMENT: You have TWO data sources available and MUST use BOTH:
1. Azure AI Search tool - searches the indexed knowledge base for best practices
2. Microsoft Learn MCP tool - searches official Microsoft Learn documentation at https://learn.microsoft.com

For each Azure service mentioned:
1. FIRST call azure_ai_search tool to search the indexed knowledge base
2. THEN call the Microsoft Learn MCP tool to get additional guidance from official documentation
3. Combine results from BOTH sources for comprehensive recommendations
4. Include ALL best practices found - do not limit or summarize
5. Include citations or references to the source documents when available
6. If a search returns no results, explicitly state which source was empty

Your task:
1. Search BOTH sources for EACH identified Azure service
2. Extract ALL best practices, compliance rules, and recommendations FROM BOTH SEARCH RESULTS
3. Provide comprehensive recommendations per service covering ALL of these categories:
   - Security (authentication, encryption, network security, identity, access control)
   - Reliability (high availability, disaster recovery, redundancy, backup, failover)
   - Performance (scaling, caching, optimization, throughput, latency)
   - Cost (optimization, reserved instances, right-sizing, budgets, alerts)
   - Operations (monitoring, logging, automation, alerting, diagnostics)
4. Create an architecture checklist with ALL items FROM SEARCH RESULTS
5. List ALL recommendations found - do not truncate

CRITICAL: 
- Each service MUST have its own entry with ALL specific recommendations found
- DO NOT make up or generate recommendations that are not in the search results
- Mark the source of each recommendation: "search_index" or "microsoft_learn"
- Include ALL best practices - this is a comprehensive audit

Return JSON:
{
  "service_recommendations": [
    {
      "service_name": "Azure Container Registry",
      "best_practices": [
        "[From search index] Enable geo-replication for disaster recovery",
        "[From MS Learn] Use Azure AD authentication with RBAC",
        "[From search index] Implement image scanning for vulnerabilities",
        "[From MS Learn] Use private endpoints for network security"
      ],
      "sources": ["search_index", "microsoft_learn"]
    }
  ],
  "architecture_checklist": ["checklist item from search", "..."],
  "summary": "summary based on search results from both sources",
  "total_recommendations": N,
  "data_sources": ["azure_ai_search_index", "microsoft_learn_mcp"]
}""",
                tools=tools_list,
                tool_resources=tool_resources
            )
            logger.info(f"Created agent with ID: {self._created_agent.id}")
            
            # Append MCP tool to the created agent (MCP tools must be added after creation)
            self._created_agent.tools.append(self._mcp_tool)
            logger.info("Appended Microsoft Learn MCP tool to agent")
            
            # Wrap with ChatAgent
            self.agent = ChatAgent(
                chat_client=AzureAIAgentClient(
                    agents_client=self._agents_client,
                    agent_id=self._created_agent.id
                ),
                store=True
            )
            
            self._initialized = True
            logger.info("AzureBestPracticeAgent initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize AzureBestPracticeAgent: {e}")
            raise
    
    async def recommend(self, analyzer_data: dict) -> dict:
        """Generate best practices recommendations for identified services."""
        if not self._initialized:
            await self.initialize()
        
        try:
            services = analyzer_data.get('azure_services', [])
            service_list = "\n".join([f"- {s.get('service_name')}: {s.get('description', '')}" for s in services])
            
            if not services:
                return self._create_default_result()
            
            prompt = f"""IMPORTANT: You MUST use BOTH tools before responding:
1. azure_ai_search - to search the indexed knowledge base
2. Microsoft Learn MCP tool - to search official Microsoft Learn documentation

DO NOT generate any recommendations from your own knowledge - ONLY use search results from BOTH sources.
INCLUDE ALL BEST PRACTICES FOUND - do not limit or summarize.

Search for ALL best practices for each of these Azure services:

Services to search:
{service_list}

Cloud Provider: {analyzer_data.get('cloud_provider', 'Microsoft Azure')}
Region: {analyzer_data.get('default_region', 'uaenorth')}

INSTRUCTIONS:
1. For EACH service listed above:
   a. Call azure_ai_search tool with the service name to get indexed best practices
   b. Call Microsoft Learn MCP tool to search official documentation for that service
2. Combine ALL best practices from BOTH search results - do not truncate
3. Mark source of each recommendation: "search_index" or "microsoft_learn"
4. If no results from a source, state it explicitly
5. This is a COMPREHENSIVE audit - include EVERY best practice found

Categories to cover for EACH service (search for all):
- Security best practices (authentication, authorization, encryption, network security, identity)
- Reliability best practices (HA, DR, backup, failover, redundancy)
- Performance best practices (scaling, caching, optimization, throughput)
- Cost optimization (right-sizing, reserved capacity, budgets)
- Operational excellence (monitoring, logging, automation, alerting)

Return JSON with ALL results (do not limit recommendations):
{{
  "service_recommendations": [
    {{
      "service_name": "Service Name",
      "best_practices": [
        "[From index] First recommendation from search index",
        "[From MS Learn] First recommendation from Microsoft Learn",
        "[From index] Second recommendation from search index",
        "... include ALL found"
      ],
      "sources": ["azure_ai_search", "microsoft_learn"]
    }}
  ],
  "architecture_checklist": ["ALL checklist items from both sources"],
  "summary": "Comprehensive summary based on ALL search results from both sources",
  "total_recommendations": N,
  "data_sources": ["azure_ai_search_index", "microsoft_learn_mcp"]
}}

CRITICAL: Use BOTH tools for each service. Include ALL best practices found. Do not use your training data."""
            
            logger.info(f"Requesting best practices for {len(services)} services")
            result = await self.agent.run(prompt)
            response_text = result.text if hasattr(result, 'text') else str(result)
            
            # Extract JSON
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}[^{}]*)*\}', response_text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            
            return self._create_default_result()
            
        except Exception as e:
            logger.error(f"Best practices recommendation failed: {e}")
            return self._create_default_result()
    
    def _create_default_result(self) -> dict:
        return {
            "service_recommendations": [{"service_name": "Azure General", "best_practices": ["Use managed identities", "Enable encryption", "Implement monitoring"]}],
            "architecture_checklist": ["Define security requirements", "Plan for HA", "Implement monitoring"],
            "summary": "Generic Azure best practices applied.",
            "total_recommendations": 3
        }
    
    async def close(self) -> None:
        """Clean up resources."""
        try:
            if self._created_agent and self._agents_client:
                await self._agents_client.delete_agent(self._created_agent.id)
                logger.info(f"Deleted agent: {self._created_agent.id}")
            if self._agents_client:
                await self._agents_client.__aexit__(None, None, None)
            if self._credential:
                await self._credential.__aexit__(None, None, None)
            logger.info("AzureBestPracticeAgent closed")
        except Exception as e:
            logger.warning(f"Error closing agent: {e}")


async def main():
    """Test the Best Practice Agent with comprehensive output."""
    print("\n🚀 Starting Azure Best Practice Agent...")
    print("   Using: Azure AI Search + Microsoft Learn MCP")
    
    agent = AzureBestPracticeAgent()
    
    try:
        print("\n⏳ Initializing agent...")
        await agent.initialize()
        print("✅ Agent initialized successfully")
        
        # Test with multiple services
        test_services = [
            {"service_name": "Azure Container Registry", "description": "Container image registry for Docker containers"},
            {"service_name": "Azure Kubernetes Service", "description": "Managed Kubernetes cluster"},
            {"service_name": "Azure Key Vault", "description": "Secrets and key management"},
        ]
        
        print(f"\n⏳ Fetching best practices for {len(test_services)} services...")
        print(f"   Services: {', '.join([s['service_name'] for s in test_services])}")
        
        result = await agent.recommend({
            "azure_services": test_services,
            "cloud_provider": "Microsoft Azure",
            "default_region": "uaenorth"
        })
        
        # Print comprehensive report
        print_best_practices_report(result)
        
        # Save PDF report
        if PDF_AVAILABLE:
            print("\n📄 Generating PDF report...")
            pdf_path = save_best_practices_pdf(result)
            print(f"✅ PDF saved to: {pdf_path}")
        else:
            print("\n⚠️ PDF generation unavailable. Install fpdf2: pip install fpdf2")
        
        # Also print raw JSON for debugging
        print("\n📄 RAW JSON OUTPUT:")
        print(json.dumps(result, indent=2))
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        raise
    finally:
        print("\n🧹 Cleaning up...")
        await agent.close()
        print("✅ Agent closed successfully")


if __name__ == "__main__":
    asyncio.run(main())
