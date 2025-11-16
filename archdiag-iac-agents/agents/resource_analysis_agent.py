"""
Resource Analysis Agent - Stage 2 of the IaC workflow.

This agent:
1. Accepts DiagramAnalysis from Computer Vision
2. Normalizes and validates resource names
3. Resolves resource dependencies
4. Enriches with Azure best practices
5. Outputs ResourceSpecification for IaC generation

Uses Microsoft Agent Framework with Azure AI Foundry.
"""

import json
import logging
from typing import Any

from agent_framework import Executor, WorkflowContext, handler
from agent_framework_azure_ai import AzureAIAgentClient
from azure.identity.aio import DefaultAzureCredential

from config import settings
from models import (
    DiagramAnalysis,
    ResourceSpecification,
    SynthesizedResource,
    ResourceDependency,
    ResourceType,
)

logger = logging.getLogger(__name__)


class ResourceAnalysisAgent(Executor):
    """
    Agent that analyzes extracted diagram data and produces normalized resource specifications.

    Responsibilities:
    - Validate and normalize Azure resource names
    - Resolve resource dependencies
    - Enrich with default configurations
    - Apply Azure naming conventions
    - Generate deployment order
    """

    def __init__(self, chat_client: AzureAIAgentClient, executor_id: str = "resource_analysis_agent"):
        """Initialize the Resource Analysis Agent."""
        # Create the AI agent with detailed instructions
        self.agent = chat_client.create_agent(
            instructions="""You are an expert Azure Solutions Architect specializing in infrastructure design and resource planning.

Your responsibilities:
1. **Resource Normalization**: Convert detected resources into valid Azure resource names following naming conventions:
   - Use lowercase letters, numbers, and hyphens
   - Start with letter, end with letter or number
   - Length appropriate for resource type (e.g., storage accounts: 3-24 chars)
   - Follow Azure naming best practices

2. **Dependency Analysis**: Identify and document resource dependencies:
   - Network dependencies (VNets must exist before VMs)
   - Storage dependencies (Storage accounts before containers)
   - Identity dependencies (Managed identities before role assignments)
   - Determine correct deployment order

3. **Configuration Enrichment**: Add sensible defaults and best practices:
   - Appropriate SKUs for workload (Standard, Premium, etc.)
   - Security settings (HTTPS only, encryption enabled)
   - High availability configurations
   - Tagging strategy

4. **Location & Resource Group**: Assign consistent locations and resource groups:
   - Use detected location or default to recommended region
   - Validate region availability for resource types
   - Group related resources in same resource group

5. **Validation**: Check for:
   - Naming conflicts
   - Invalid configurations
   - Missing required properties
   - Security concerns

OUTPUT FORMAT:
Return a JSON object with this structure:
{
    "default_location": "eastus",
    "default_resource_group": "rg-infrastructure",
    "resources": [
        {
            "resource_name": "storage001",
            "resource_type": "Microsoft.Storage/storageAccounts",
            "location": "eastus",
            "resource_group": "rg-infrastructure",
            "sku": "Standard_LRS",
            "properties": {
                "encryption": {"services": {"blob": {"enabled": true}}},
                "supportsHttpsTrafficOnly": true
            },
            "tags": {"environment": "production", "managed-by": "iac"},
            "depends_on": [],
            "deployment_order": 1,
            "notes": ["Using Standard_LRS for cost optimization"]
        }
    ],
    "dependencies": [
        {
            "source": "vm-001",
            "target": "vnet-001",
            "dependency_type": "network"
        }
    ],
    "parameters": {
        "location": {"type": "string", "defaultValue": "eastus"},
        "environment": {"type": "string", "defaultValue": "prod"}
    },
    "validation_notes": [
        "All resources use consistent naming convention",
        "Dependencies properly ordered"
    ]
}

Be thorough, follow Azure best practices, and ensure resources can be deployed successfully.""",
        )
        super().__init__(id=executor_id)

    @handler
    async def analyze_resources(
        self,
        diagram_analysis: DiagramAnalysis,
        ctx: WorkflowContext[ResourceSpecification],
    ) -> None:
        """
        Analyze diagram and create normalized resource specification.

        Args:
            diagram_analysis: Output from Computer Vision analysis
            ctx: Workflow context for sending results
        """
        logger.info(f"Analyzing {len(diagram_analysis.resources)} detected resources")

        # Prepare the prompt with extracted resource information
        resources_summary = self._prepare_resources_summary(diagram_analysis)

        prompt = f"""Analyze these resources extracted from an architecture diagram and create a complete Azure resource specification.

**Extracted Resources:**
{resources_summary}

**Detected Text Context:**
{chr(10).join(diagram_analysis.detected_text[:20])}  # First 20 lines

**Instructions:**
1. Normalize all resource names to follow Azure naming conventions
2. Assign appropriate SKUs and configurations for each resource type
3. Identify and document all dependencies between resources
4. Set deployment order based on dependencies
5. Add Azure tags for governance
6. Include validation notes about the infrastructure

Return the complete JSON specification following the format provided in your instructions.
"""

        logger.debug(f"Sending analysis request to AI agent")

        # Run the agent to analyze and synthesize
        response = await self.agent.run([{"role": "user", "content": prompt}])

        # Extract JSON from response
        response_text = response.text
        logger.debug(f"Agent response: {response_text[:500]}...")

        # Parse JSON response
        try:
            spec_data = self._extract_json_from_response(response_text)
            
            # Build ResourceSpecification model
            resource_spec = self._build_resource_specification(
                spec_data, diagram_analysis
            )

            logger.info(
                f"Resource analysis complete: {resource_spec.total_resources} resources, "
                f"{len(resource_spec.dependencies)} dependencies"
            )

            # Send to next agent
            await ctx.send_message(resource_spec)

        except Exception as e:
            logger.error(f"Failed to parse agent response: {e}", exc_info=True)
            # Create fallback specification
            resource_spec = self._create_fallback_specification(diagram_analysis)
            logger.warning("Using fallback resource specification")
            await ctx.send_message(resource_spec)

    def _prepare_resources_summary(self, diagram_analysis: DiagramAnalysis) -> str:
        """Prepare a formatted summary of extracted resources."""
        lines = []
        for idx, resource in enumerate(diagram_analysis.resources, 1):
            lines.append(
                f"{idx}. Name: '{resource.detected_name}' | "
                f"Type: {resource.resource_type.value} | "
                f"Confidence: {resource.confidence_score:.2f} | "
                f"Properties: {resource.properties} | "
                f"Connected to: {', '.join(resource.connected_to) if resource.connected_to else 'none'}"
            )
        return "\n".join(lines)

    def _extract_json_from_response(self, response_text: str) -> dict[str, Any]:
        """Extract JSON from agent response text."""
        # Try to find JSON in response (may be wrapped in markdown code blocks)
        import re

        # Remove markdown code blocks
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find raw JSON
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                raise ValueError("No JSON found in response")

        return json.loads(json_str)

    def _build_resource_specification(
        self, spec_data: dict[str, Any], diagram_analysis: DiagramAnalysis
    ) -> ResourceSpecification:
        """Build ResourceSpecification model from agent response."""
        # Parse resources
        resources = [
            SynthesizedResource(
                resource_name=r["resource_name"],
                resource_type=ResourceType(r["resource_type"])
                if r["resource_type"] in [rt.value for rt in ResourceType]
                else ResourceType.UNKNOWN,
                location=r.get("location", spec_data.get("default_location", "eastus")),
                resource_group=r.get(
                    "resource_group", spec_data.get("default_resource_group", "rg-infrastructure")
                ),
                sku=r.get("sku"),
                properties=r.get("properties", {}),
                tags=r.get("tags", {}),
                depends_on=r.get("depends_on", []),
                deployment_order=r.get("deployment_order", 0),
                notes=r.get("notes", []),
            )
            for r in spec_data.get("resources", [])
        ]

        # Parse dependencies
        dependencies = [
            ResourceDependency(
                source=d["source"],
                target=d["target"],
                dependency_type=d["dependency_type"],
            )
            for d in spec_data.get("dependencies", [])
        ]

        # Calculate resource type summary
        resource_types_summary = {}
        for resource in resources:
            rt = resource.resource_type.value
            resource_types_summary[rt] = resource_types_summary.get(rt, 0) + 1

        return ResourceSpecification(
            source_diagram=diagram_analysis.image_filename,
            default_location=spec_data.get("default_location", "eastus"),
            default_resource_group=spec_data.get(
                "default_resource_group", "rg-infrastructure"
            ),
            resources=resources,
            dependencies=dependencies,
            parameters=spec_data.get("parameters", {}),
            total_resources=len(resources),
            resource_types_summary=resource_types_summary,
            validation_notes=spec_data.get("validation_notes", []),
        )

    def _create_fallback_specification(
        self, diagram_analysis: DiagramAnalysis
    ) -> ResourceSpecification:
        """Create a basic fallback specification if agent fails."""
        logger.warning("Creating fallback specification")

        resources = []
        for idx, extracted in enumerate(diagram_analysis.resources, 1):
            if extracted.resource_type == ResourceType.UNKNOWN:
                continue

            resource = SynthesizedResource(
                resource_name=extracted.detected_name.lower().replace(" ", "-"),
                resource_type=extracted.resource_type,
                location=extracted.properties.get("location", "eastus"),
                resource_group="rg-infrastructure",
                sku="Standard",
                properties=extracted.properties,
                tags={"source": "diagram-analysis", "managed-by": "iac"},
                depends_on=[],
                deployment_order=idx,
                notes=["Fallback specification - manual review recommended"],
            )
            resources.append(resource)

        return ResourceSpecification(
            source_diagram=diagram_analysis.image_filename,
            default_location="eastus",
            default_resource_group="rg-infrastructure",
            resources=resources,
            dependencies=[],
            parameters={},
            total_resources=len(resources),
            resource_types_summary={},
            validation_notes=["Fallback specification generated due to agent error"],
        )


def create_resource_analysis_agent(
    chat_client: AzureAIAgentClient,
) -> ResourceAnalysisAgent:
    """Factory function to create a ResourceAnalysisAgent instance."""
    return ResourceAnalysisAgent(chat_client)


async def create_resource_analysis_agent_with_client() -> ResourceAnalysisAgent:
    """Create agent with a new AI client."""
    async with DefaultAzureCredential() as credential:
        chat_client = AzureAIAgentClient(
            project_endpoint=settings.azure_ai.project_endpoint,
            model_deployment_name=settings.azure_ai.model_deployment_name,
            async_credential=credential,
            agent_name="ResourceAnalysisAgent",
        )
        return create_resource_analysis_agent(chat_client)
