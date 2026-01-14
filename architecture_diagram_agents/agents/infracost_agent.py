"""
Infracost Agent - Agentic cost estimation using Azure AI with Infracost CLI as a tool.
The agent analyzes Terraform plan costs and generates comprehensive reports.
Uses plan.json as input and produces infracost.json for LLM augmentation.
"""

import asyncio
import os
import json
import subprocess
import shutil
from typing import Dict, Any

from azure.identity.aio import AzureCliCredential
from azure.identity import AzureCliCredential as SyncAzureCliCredential
from azure.ai.agents.aio import AgentsClient
from agent_framework.azure import AzureAIAgentClient
from agent_framework import ChatAgent
from dotenv import load_dotenv

from ..utils.legacy_utils import setup_logger
from ..utils.logging_config import setup_logging

# Load .env from project root
env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=env_path, override=True)

# Initialize logging
setup_logging(level="INFO")
logger = setup_logger(__name__)

# Configuration
INFRACOST_API_KEY = os.environ.get("INFRACOST_API_KEY")
PROJECT_ENDPOINT = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
MODEL_DEPLOYMENT_NAME = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4o-mini")

# Set env vars for AIProjectClient if not already set
if PROJECT_ENDPOINT and not os.environ.get("AI_FOUNDRY_PROJECT_ENDPOINT"):
    os.environ["AI_FOUNDRY_PROJECT_ENDPOINT"] = PROJECT_ENDPOINT


def run_infracost_breakdown(terraform_project_path: str) -> str:
    """
    Run Infracost CLI to estimate infrastructure costs from terraform plan.json.
    
    This tool uses the Infracost CLI to analyze a Terraform project directory 
    containing plan.json and generates infracost.json with detailed cost breakdown.
    
    Args:
        terraform_project_path: Absolute path to the terraform project directory 
                               containing plan.json or .tf files
    
    Returns:
        JSON string with detailed cost breakdown by resource including monthly and hourly costs,
        or error information if the operation fails.
    """
    if not terraform_project_path or not os.path.isdir(terraform_project_path):
        return json.dumps({"error": f"Invalid terraform project path: {terraform_project_path}"})
    
    # Check if infracost CLI is available
    infracost_exe = shutil.which("infracost")
    if not infracost_exe:
        return json.dumps({"error": "Infracost CLI not found in PATH. Install from https://www.infracost.io/docs/"})
    
    # Check if INFRACOST_API_KEY is set
    if not INFRACOST_API_KEY:
        return json.dumps({"error": "INFRACOST_API_KEY environment variable not set"})
    
    # Determine input - prefer plan.json if available, otherwise use HCL files
    plan_json_path = os.path.join(terraform_project_path, "plan.json")
    infracost_output_path = os.path.join(terraform_project_path, "infracost.json")
    
    try:
        # Build infracost command
        if os.path.exists(plan_json_path):
            logger.info(f"[Infracost] Using plan.json from: {plan_json_path}")
            cmd = [
                infracost_exe, "breakdown",
                "--path", plan_json_path,
                "--format", "json",
                "--out-file", infracost_output_path
            ]
        else:
            logger.info(f"[Infracost] No plan.json found, using HCL files from: {terraform_project_path}")
            cmd = [
                infracost_exe, "breakdown",
                "--path", terraform_project_path,
                "--format", "json",
                "--out-file", infracost_output_path
            ]
        
        logger.info(f"[Infracost] Running: {' '.join(cmd)}")
        
        # Run infracost CLI
        result = subprocess.run(
            cmd,
            cwd=terraform_project_path,
            capture_output=True,
            text=True,
            timeout=300,  # 5 min timeout
            env={**os.environ, "INFRACOST_API_KEY": INFRACOST_API_KEY}
        )
        
        if result.returncode != 0:
            error_msg = result.stderr or result.stdout
            logger.error(f"[Infracost] CLI failed: {error_msg}")
            return json.dumps({
                "error": f"Infracost CLI failed with exit code {result.returncode}",
                "details": error_msg[:1000]
            })
        
        # Read the generated infracost.json
        if not os.path.exists(infracost_output_path):
            return json.dumps({"error": "Infracost output file was not created"})
        
        with open(infracost_output_path, 'r', encoding='utf-8') as f:
            cost_data = json.load(f)
        
        logger.info(f"[Infracost] Successfully generated: {infracost_output_path}")
        
        # Extract and format key metrics for the LLM
        formatted_result = {
            "status": "SUCCESS",
            "infracost_json_path": infracost_output_path,
            "currency": cost_data.get("currency", "USD"),
            "total_monthly_cost": cost_data.get("totalMonthlyCost", "0"),
            "total_hourly_cost": cost_data.get("totalHourlyCost", "0"),
            "past_total_monthly_cost": cost_data.get("pastTotalMonthlyCost", "0"),
            "diff_total_monthly_cost": cost_data.get("diffTotalMonthlyCost", "0"),
            "time_generated": cost_data.get("timeGenerated", ""),
            "resources": [],
            "summary": {}
        }
        
        # Extract resources from projects
        projects = cost_data.get("projects", [])
        for project in projects:
            project_name = project.get("name", "Unknown")
            breakdown = project.get("breakdown", {})
            
            for resource in breakdown.get("resources", []):
                resource_info = {
                    "project": project_name,
                    "name": resource.get("name", "Unknown"),
                    "resource_type": resource.get("resourceType", "Unknown"),
                    "monthly_cost": resource.get("monthlyCost", "0"),
                    "hourly_cost": resource.get("hourlyCost", "0"),
                    "metadata": resource.get("metadata", {}),
                    "cost_components": []
                }
                
                for cc in resource.get("costComponents", []):
                    resource_info["cost_components"].append({
                        "name": cc.get("name"),
                        "unit": cc.get("unit"),
                        "unit_price": cc.get("price"),
                        "monthly_quantity": cc.get("monthlyQuantity"),
                        "monthly_cost": cc.get("monthlyCost", "0"),
                    })
                
                # Include sub-resources if any
                for sub_resource in resource.get("subresources", []):
                    sub_info = {
                        "project": project_name,
                        "name": f"{resource.get('name', '')}/{sub_resource.get('name', '')}",
                        "resource_type": sub_resource.get("resourceType", "subresource"),
                        "monthly_cost": sub_resource.get("monthlyCost", "0"),
                        "hourly_cost": sub_resource.get("hourlyCost", "0"),
                        "cost_components": []
                    }
                    for cc in sub_resource.get("costComponents", []):
                        sub_info["cost_components"].append({
                            "name": cc.get("name"),
                            "unit": cc.get("unit"),
                            "unit_price": cc.get("price"),
                            "monthly_quantity": cc.get("monthlyQuantity"),
                            "monthly_cost": cc.get("monthlyCost", "0"),
                        })
                    formatted_result["resources"].append(sub_info)
                
                formatted_result["resources"].append(resource_info)
        
        # Add summary
        formatted_result["resource_count"] = len(formatted_result["resources"])
        formatted_result["summary"] = {
            "total_resources": formatted_result["resource_count"],
            "total_monthly_cost": formatted_result["total_monthly_cost"],
            "total_hourly_cost": formatted_result["total_hourly_cost"],
            "currency": formatted_result["currency"]
        }
        
        return json.dumps(formatted_result)
        
    except subprocess.TimeoutExpired:
        logger.error("[Infracost] CLI command timed out")
        return json.dumps({"error": "Infracost CLI timed out after 5 minutes"})
    except Exception as e:
        logger.error(f"[Infracost] Error: {e}", exc_info=True)
        return json.dumps({"error": str(e)})


class InfracostAgent:
    """
    Agentic cost estimation agent that uses Infracost CLI as a tool.
    Analyzes terraform plan.json costs and generates comprehensive reports with recommendations.
    """
    
    AGENT_INSTRUCTIONS = """You are an Azure infrastructure cost analysis expert. Your role is to:

1. FIRST: Call the run_infracost_breakdown tool with the terraform project path to get cost estimates
2. THEN: Analyze the results and create a comprehensive cost report

**IMPORTANT**: You MUST call the run_infracost_breakdown tool first before generating any report.

**Report Format** (use this exact structure):

## 💰 INFRASTRUCTURE COST REPORT

### Executive Summary
- Total Monthly Cost: $X.XX
- Total Hourly Cost: $X.XX
- Total Resources: N
- Currency: USD

### 📊 Cost Breakdown by Resource (Top 10 by cost)
| Resource | Type | Monthly Cost | Hourly Cost |
|----------|------|--------------|-------------|
| ... | ... | $X.XX | $X.XX |

### 📈 Cost Components Detail
For each major resource, list the cost components that make up its cost.

### 💡 Cost Optimization Recommendations
1. [Specific recommendation based on the resources - e.g., reserved instances, right-sizing]
2. [Another recommendation]
3. [etc.]

### ⚠️ High-Cost Alerts
- [List any resources costing more than $100/month with specific details]

### 💵 Potential Savings
- Estimated monthly savings with optimizations: $X.XX
- Specific savings opportunities identified

### 📋 Summary
Provide a brief executive summary of the infrastructure costs and key takeaways.

Be specific, actionable, and base all recommendations on the actual cost data returned."""

    def __init__(self):
        self.agent: ChatAgent = None
        self._agents_client = None
        self._credential = None
        self._created_agent = None
        self._initialized = False
        logger.info("InfracostAgent instantiated")
    
    async def initialize(self) -> None:
        """Initialize the Azure AI agent with Infracost tool."""
        if self._initialized:
            return
        
        try:
            self._credential = AzureCliCredential()
            self._agents_client = AgentsClient(
                endpoint=PROJECT_ENDPOINT,
                credential=self._credential
            )
            await self._agents_client.__aenter__()
            
            logger.info(f"Initializing InfracostAgent with model: {MODEL_DEPLOYMENT_NAME}")
            
            # Create persistent agent via AgentsClient
            self._created_agent = await self._agents_client.create_agent(
                model=MODEL_DEPLOYMENT_NAME,
                name="InfracostAnalyzer",
                instructions=self.AGENT_INSTRUCTIONS
            )
            
            logger.info(f"Created agent with ID: {self._created_agent.id}")
            
            # Wrap agent with ChatAgent and tools
            self.agent = ChatAgent(
                chat_client=AzureAIAgentClient(
                    agents_client=self._agents_client,
                    agent_id=self._created_agent.id
                ),
                tools=[
                    run_infracost_breakdown,  # Pass function directly - framework generates schema
                ],
                store=True
            )
            
            self._initialized = True
            logger.info("InfracostAgent initialized successfully with tool: run_infracost_breakdown")
            
        except Exception as e:
            logger.error(f"Failed to initialize InfracostAgent: {e}")
            raise
    
    async def estimate(self, terraform_path: str, terraform_data: Dict[str, str] = None) -> Dict[str, Any]:
        """
        Estimate infrastructure costs using Infracost CLI and generate a comprehensive report.
        
        Args:
            terraform_path: Path to the terraform project directory containing plan.json
            terraform_data: Optional dict containing terraform file contents (for backwards compatibility)
            
        Returns:
            Dictionary with cost estimates, infracost.json path, and AI-generated report
        """
        if not terraform_path:
            return {"status": "ERROR", "error": "No terraform path provided"}
        
        if not os.path.isdir(terraform_path):
            return {"status": "ERROR", "error": f"Invalid terraform path: {terraform_path}"}
        
        # Initialize agent if not already done
        await self.initialize()
        
        # Check what files are available
        plan_json_exists = os.path.exists(os.path.join(terraform_path, "plan.json"))
        main_tf_exists = os.path.exists(os.path.join(terraform_path, "main.tf"))
        
        prompt = f"""Analyze the infrastructure costs for the Terraform project.

**Terraform Project Path:** {terraform_path}

**Available Files:**
- plan.json: {"✓ Available" if plan_json_exists else "✗ Not available"}
- main.tf: {"✓ Available" if main_tf_exists else "✗ Not available"}

**Instructions:**
1. Call the run_infracost_breakdown tool with terraform_project_path="{terraform_path}"
2. The tool will use plan.json if available, otherwise it will analyze the .tf files directly
3. Generate a comprehensive cost report based on the results

Please proceed with the cost analysis."""

        logger.info(f"Running InfracostAgent for path: {terraform_path}")
        
        try:
            # Run agent - framework handles tool calling automatically
            result = await self.agent.run(prompt)
            
            final_report = result.text if hasattr(result, 'text') else str(result)
            
            # Read infracost.json if it was generated
            infracost_json_path = os.path.join(terraform_path, "infracost.json")
            cost_data = {}
            
            if os.path.exists(infracost_json_path):
                try:
                    with open(infracost_json_path, 'r', encoding='utf-8') as f:
                        raw_cost_data = json.load(f)
                    
                    # Extract summary from raw infracost output
                    cost_data = {
                        "currency": raw_cost_data.get("currency", "USD"),
                        "total_monthly_cost": raw_cost_data.get("totalMonthlyCost", "0"),
                        "total_hourly_cost": raw_cost_data.get("totalHourlyCost", "0"),
                        "resources": []
                    }
                    
                    # Extract resources
                    for project in raw_cost_data.get("projects", []):
                        breakdown = project.get("breakdown", {})
                        for resource in breakdown.get("resources", []):
                            cost_data["resources"].append({
                                "name": resource.get("name", "Unknown"),
                                "resource_type": resource.get("resourceType", "Unknown"),
                                "monthly_cost": resource.get("monthlyCost", "0"),
                                "hourly_cost": resource.get("hourlyCost", "0"),
                            })
                    
                    cost_data["resource_count"] = len(cost_data["resources"])
                    logger.info(f"Loaded cost data from: {infracost_json_path}")
                    
                except Exception as e:
                    logger.warning(f"Failed to read infracost.json: {e}")
            
            # Build result
            return {
                "status": "SUCCESS",
                "terraform_path": terraform_path,
                "infracost_json_path": infracost_json_path if os.path.exists(infracost_json_path) else None,
                "cost_estimate": {
                    "summary": {
                        "currency": cost_data.get("currency", "USD"),
                        "total_monthly_cost": f"${cost_data.get('total_monthly_cost', '0')}",
                        "total_hourly_cost": f"${cost_data.get('total_hourly_cost', '0')}",
                    },
                    "resource_count": cost_data.get("resource_count", 0),
                    "resources": cost_data.get("resources", []),
                },
                "report": final_report,
                "error": None
            }
            
        except Exception as e:
            logger.error(f"InfracostAgent estimation failed: {e}", exc_info=True)
            return {"status": "ERROR", "error": str(e)}
    
    async def close(self) -> None:
        """Clean up agent resources."""
        try:
            # Delete the created agent if it exists
            if self._agents_client and self._created_agent:
                try:
                    await self._agents_client.delete_agent(self._created_agent.id)
                    logger.info(f"Deleted agent: {self._created_agent.id}")
                except Exception as e:
                    logger.warning(f"Failed to delete agent: {e}")
            
            # Close agents client
            if self._agents_client:
                await self._agents_client.__aexit__(None, None, None)
            
            # Close credential
            if self._credential:
                await self._credential.close()
                
        except Exception as e:
            logger.warning(f"Error during cleanup: {e}")
        finally:
            self._initialized = False
            logger.info("InfracostAgent closed")
