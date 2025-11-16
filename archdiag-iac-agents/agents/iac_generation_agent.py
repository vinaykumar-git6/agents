"""
IaC Generation Agent - Stage 3 of the IaC workflow.

This agent:
1. Accepts ResourceSpecification from Resource Analysis
2. Generates complete Bicep infrastructure as code
3. Applies Azure best practices and security guidelines
4. Creates parameters, variables, and outputs
5. Outputs BicepCode for review

Uses Microsoft Agent Framework with Azure AI Foundry.
"""

import json
import logging
import re
from typing import Any

from agent_framework import Executor, WorkflowContext, handler
from agent_framework_azure_ai import AzureAIAgentClient
from azure.identity.aio import DefaultAzureCredential

from config import settings
from models import (
    ResourceSpecification,
    BicepCode,
    BicepParameter,
    BicepVariable,
    BicepResource,
    BicepOutput,
)

logger = logging.getLogger(__name__)


class IaCGenerationAgent(Executor):
    """
    Agent that generates Bicep infrastructure as code from resource specifications.

    Responsibilities:
    - Generate complete Bicep templates
    - Apply Azure best practices
    - Create parameterized templates
    - Add security configurations
    - Generate outputs for deployed resources
    """

    def __init__(self, chat_client: AzureAIAgentClient, executor_id: str = "iac_generation_agent"):
        """Initialize the IaC Generation Agent."""
        self.agent = chat_client.create_agent(
            instructions="""You are an expert Azure Infrastructure as Code (IaC) developer specializing in Bicep templates.

Your responsibilities:
1. **Bicep Template Generation**: Create complete, production-ready Bicep templates:
   - Use latest Bicep syntax and features
   - Follow Azure Resource Manager (ARM) best practices
   - Use symbolic names for resources
   - Implement proper resource dependencies with dependsOn

2. **Parameterization**: Create flexible, reusable templates:
   - Extract environment-specific values as parameters
   - Use appropriate parameter types and validation
   - Provide sensible default values
   - Add parameter descriptions

3. **Variables**: Define variables for:
   - Computed values and expressions
   - Resource naming patterns
   - Common configuration blocks
   - API versions

4. **Security Best Practices**:
   - Enable encryption at rest and in transit
   - Use managed identities where possible
   - Configure HTTPS/TLS only
   - Apply network security rules
   - Enable Azure Defender/monitoring

5. **Resource Properties**:
   - Use latest stable API versions
   - Configure high availability options
   - Enable diagnostic settings
   - Add resource tags
   - Set appropriate SKUs

6. **Outputs**: Expose important resource information:
   - Resource IDs
   - Endpoint URLs
   - Connection strings (via Key Vault references)
   - Managed identity principal IDs

7. **Code Quality**:
   - Clean, readable code with comments
   - Consistent indentation and formatting
   - Logical resource ordering
   - Helpful inline documentation

OUTPUT FORMAT:
Return a JSON object with complete Bicep code:
{
    "parameters": [
        {
            "name": "location",
            "type": "string",
            "default_value": "eastus",
            "description": "Azure region for resources"
        }
    ],
    "variables": [
        {
            "name": "storageAccountName",
            "value": "format('stor{0}', uniqueString(resourceGroup().id))",
            "description": "Generated storage account name"
        }
    ],
    "resources": [
        {
            "symbolic_name": "storageAccount",
            "resource_type": "Microsoft.Storage/storageAccounts",
            "api_version": "2023-01-01",
            "name_expression": "storageAccountName",
            "properties": {...},
            "depends_on": []
        }
    ],
    "outputs": [
        {
            "name": "storageAccountId",
            "type": "string",
            "value_expression": "storageAccount.id",
            "description": "Resource ID of storage account"
        }
    ],
    "bicep_code": "// Complete Bicep template code here...",
    "generation_notes": ["Applied security best practices", "Using managed identity"]
}

Generate secure, production-ready Bicep code following Microsoft's Azure Well-Architected Framework.""",
        )
        super().__init__(id=executor_id)

    @handler
    async def generate_bicep(
        self,
        resource_spec: ResourceSpecification,
        ctx: WorkflowContext[BicepCode],
    ) -> None:
        """
        Generate Bicep infrastructure code from resource specification.

        Args:
            resource_spec: Analyzed and normalized resource specification
            ctx: Workflow context for sending results
        """
        logger.info(f"Generating Bicep for {resource_spec.total_resources} resources")

        # Prepare resource specification summary
        spec_summary = self._prepare_spec_summary(resource_spec)

        prompt = f"""Generate a complete Bicep infrastructure as code template for the following Azure resources.

**Resource Specification:**
{spec_summary}

**Requirements:**
1. Create a complete, deployable Bicep template
2. Use parameters for environment-specific values (location, environment, etc.)
3. Apply Azure security best practices
4. Include proper resource dependencies
5. Add diagnostic settings where applicable
6. Generate useful outputs
7. Add comments explaining key configurations

**Important:**
- Use latest stable API versions for each resource type
- Enable HTTPS only for all services
- Use managed identities where supported
- Configure encryption at rest
- Add resource tags for governance
- Follow Azure naming conventions

Return the complete JSON structure with the full Bicep code in the 'bicep_code' field.
"""

        logger.debug("Sending Bicep generation request to AI agent")

        # Run the agent to generate Bicep code
        response = await self.agent.run([{"role": "user", "content": prompt}])

        response_text = response.text
        logger.debug(f"Agent response length: {len(response_text)} characters")

        # Parse JSON response
        try:
            bicep_data = self._extract_json_from_response(response_text)

            # Build BicepCode model
            bicep_code = self._build_bicep_code(bicep_data, resource_spec)

            logger.info(
                f"Bicep generation complete: {len(bicep_code.resources)} resources, "
                f"{len(bicep_code.parameters)} parameters, "
                f"{len(bicep_code.outputs)} outputs"
            )

            # Send to next agent
            await ctx.send_message(bicep_code)

        except Exception as e:
            logger.error(f"Failed to generate Bicep code: {e}", exc_info=True)
            # Create fallback Bicep
            bicep_code = self._create_fallback_bicep(resource_spec)
            logger.warning("Using fallback Bicep template")
            await ctx.send_message(bicep_code)

    def _prepare_spec_summary(self, resource_spec: ResourceSpecification) -> str:
        """Prepare formatted summary of resource specification."""
        lines = [
            f"**Default Location:** {resource_spec.default_location}",
            f"**Default Resource Group:** {resource_spec.default_resource_group}",
            f"**Total Resources:** {resource_spec.total_resources}",
            "",
            "**Resources:**",
        ]

        for resource in sorted(resource_spec.resources, key=lambda r: r.deployment_order):
            lines.append(
                f"  {resource.deployment_order}. {resource.resource_name} "
                f"({resource.resource_type.value})"
            )
            lines.append(f"     Location: {resource.location}")
            if resource.sku:
                lines.append(f"     SKU: {resource.sku}")
            if resource.depends_on:
                lines.append(f"     Depends on: {', '.join(resource.depends_on)}")
            if resource.properties:
                lines.append(f"     Properties: {json.dumps(resource.properties, indent=6)}")

        if resource_spec.dependencies:
            lines.append("")
            lines.append("**Dependencies:**")
            for dep in resource_spec.dependencies:
                lines.append(f"  - {dep.source} → {dep.target} ({dep.dependency_type})")

        return "\n".join(lines)

    def _extract_json_from_response(self, response_text: str) -> dict[str, Any]:
        """Extract JSON from agent response."""
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

    def _build_bicep_code(
        self, bicep_data: dict[str, Any], resource_spec: ResourceSpecification
    ) -> BicepCode:
        """Build BicepCode model from agent response."""
        # Parse parameters
        parameters = [
            BicepParameter(
                name=p["name"],
                type=p["type"],
                default_value=p.get("default_value"),
                description=p.get("description"),
                allowed_values=p.get("allowed_values"),
            )
            for p in bicep_data.get("parameters", [])
        ]

        # Parse variables
        variables = [
            BicepVariable(
                name=v["name"],
                value=v["value"],
                description=v.get("description"),
            )
            for v in bicep_data.get("variables", [])
        ]

        # Parse resources
        resources = [
            BicepResource(
                symbolic_name=r["symbolic_name"],
                resource_type=r["resource_type"],
                api_version=r["api_version"],
                name_expression=r["name_expression"],
                properties=r.get("properties", {}),
                depends_on=r.get("depends_on", []),
            )
            for r in bicep_data.get("resources", [])
        ]

        # Parse outputs
        outputs = [
            BicepOutput(
                name=o["name"],
                type=o["type"],
                value_expression=o["value_expression"],
                description=o.get("description"),
            )
            for o in bicep_data.get("outputs", [])
        ]

        # Get complete Bicep code
        bicep_code_str = bicep_data.get("bicep_code", "")

        # If bicep_code is empty, generate basic template
        if not bicep_code_str.strip():
            bicep_code_str = self._generate_basic_bicep_template(
                parameters, variables, resources, outputs
            )

        return BicepCode(
            source_specification=resource_spec.source_diagram,
            parameters=parameters,
            variables=variables,
            resources=resources,
            outputs=outputs,
            bicep_code=bicep_code_str,
            target_scope="resourceGroup",
            version="1.0",
            generation_notes=bicep_data.get("generation_notes", []),
        )

    def _generate_basic_bicep_template(
        self,
        parameters: list[BicepParameter],
        variables: list[BicepVariable],
        resources: list[BicepResource],
        outputs: list[BicepOutput],
    ) -> str:
        """Generate basic Bicep template from components."""
        lines = [
            "// Generated Bicep Template",
            "// Auto-generated from architecture diagram",
            "",
            "targetScope = 'resourceGroup'",
            "",
        ]

        # Parameters
        if parameters:
            lines.append("// Parameters")
            for param in parameters:
                lines.append(f"@description('{param.description or param.name}')")
                if param.default_value is not None:
                    lines.append(f"param {param.name} {param.type} = '{param.default_value}'")
                else:
                    lines.append(f"param {param.name} {param.type}")
                lines.append("")

        # Variables
        if variables:
            lines.append("// Variables")
            for var in variables:
                if var.description:
                    lines.append(f"// {var.description}")
                lines.append(f"var {var.name} = {var.value}")
            lines.append("")

        # Resources
        if resources:
            lines.append("// Resources")
            for resource in resources:
                lines.append(f"resource {resource.symbolic_name} '{resource.resource_type}@{resource.api_version}' = {{")
                lines.append(f"  name: {resource.name_expression}")
                lines.append(f"  location: location")
                if resource.properties:
                    lines.append(f"  properties: {json.dumps(resource.properties, indent=4)}")
                if resource.depends_on:
                    lines.append(f"  dependsOn: [")
                    for dep in resource.depends_on:
                        lines.append(f"    {dep}")
                    lines.append(f"  ]")
                lines.append("}")
                lines.append("")

        # Outputs
        if outputs:
            lines.append("// Outputs")
            for output in outputs:
                if output.description:
                    lines.append(f"@description('{output.description}')")
                lines.append(f"output {output.name} {output.type} = {output.value_expression}")
            lines.append("")

        return "\n".join(lines)

    def _create_fallback_bicep(self, resource_spec: ResourceSpecification) -> BicepCode:
        """Create basic fallback Bicep template."""
        logger.warning("Creating fallback Bicep template")

        # Basic parameter
        parameters = [
            BicepParameter(
                name="location",
                type="string",
                default_value=resource_spec.default_location,
                description="Azure region for resources",
            )
        ]

        # Basic resource representations
        resources = [
            BicepResource(
                symbolic_name=resource.resource_name.replace("-", "_"),
                resource_type=resource.resource_type.value,
                api_version="2023-01-01",  # Generic version
                name_expression=f"'{resource.resource_name}'",
                properties=resource.properties,
                depends_on=[],
            )
            for resource in resource_spec.resources
        ]

        # Generate basic template
        bicep_code_str = self._generate_basic_bicep_template(parameters, [], resources, [])

        return BicepCode(
            source_specification=resource_spec.source_diagram,
            parameters=parameters,
            variables=[],
            resources=resources,
            outputs=[],
            bicep_code=bicep_code_str,
            target_scope="resourceGroup",
            version="1.0",
            generation_notes=["Fallback template - manual review required"],
        )


def create_iac_generation_agent(
    chat_client: AzureAIAgentClient,
) -> IaCGenerationAgent:
    """Factory function to create an IaCGenerationAgent instance."""
    return IaCGenerationAgent(chat_client)


async def create_iac_generation_agent_with_client() -> IaCGenerationAgent:
    """Create agent with a new AI client."""
    async with DefaultAzureCredential() as credential:
        chat_client = AzureAIAgentClient(
            project_endpoint=settings.azure_ai.project_endpoint,
            model_deployment_name=settings.azure_ai.model_deployment_name,
            async_credential=credential,
            agent_name="IaCGenerationAgent",
        )
        return create_iac_generation_agent(chat_client)
