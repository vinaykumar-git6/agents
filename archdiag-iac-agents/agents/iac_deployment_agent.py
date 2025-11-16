"""
IaC Deployment Agent - Stage 5 of the IaC workflow.

This agent:
1. Accepts ValidationResult (with BicepCode embedded in context)
2. Deploys Bicep template to Azure using Azure SDK
3. Monitors deployment progress
4. Collects deployment outputs
5. Handles errors and rollback
6. Outputs DeploymentResult

Uses Microsoft Agent Framework with Azure Management SDK.
"""

import asyncio
import json
import logging
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

from agent_framework import Executor, WorkflowContext, handler
from agent_framework_azure_ai import AzureAIAgentClient
from azure.identity.aio import DefaultAzureCredential
from azure.mgmt.resource.aio import ResourceManagementClient
from azure.mgmt.resource.resources.models import (
    Deployment,
    DeploymentProperties,
    DeploymentMode,
)

from config import settings
from models import (
    ValidationResult,
    BicepCode,
    DeploymentResult,
    DeploymentStatus,
    DeployedResource,
)

logger = logging.getLogger(__name__)


class IaCDeploymentAgent(Executor):
    """
    Agent that deploys validated Bicep infrastructure to Azure.

    Responsibilities:
    - Compile Bicep to ARM JSON
    - Create Azure deployment
    - Monitor deployment progress
    - Handle deployment errors
    - Collect deployment outputs
    - Report deployment status
    """

    def __init__(
        self,
        chat_client: Optional[AzureAIAgentClient] = None,
        executor_id: str = "iac_deployment_agent",
    ):
        """Initialize the IaC Deployment Agent."""
        # This agent may not need AI client for deployment (pure SDK operations)
        # But can use it for analyzing errors or providing recommendations
        if chat_client:
            self.agent = chat_client.create_agent(
                instructions="""You are an Azure deployment specialist helping to analyze deployment errors and provide remediation guidance.

When a deployment fails:
1. Analyze the error message and code
2. Identify the root cause
3. Provide specific remediation steps
4. Suggest alternative approaches if needed

Be concise and action-oriented.""",
            )
        else:
            self.agent = None

        super().__init__(id=executor_id)

    @handler
    async def deploy_infrastructure(
        self,
        validation_result: ValidationResult,
        ctx: WorkflowContext[Any, DeploymentResult],
    ) -> None:
        """
        Deploy validated Bicep infrastructure to Azure.

        Args:
            validation_result: Validation result with bicep code
            ctx: Workflow context for yielding deployment result

        Note: BicepCode should be passed via workflow state or context
        """
        logger.info("Starting infrastructure deployment to Azure")

        # Check if deployment should proceed
        if validation_result.has_critical_issues:
            logger.error("Cannot deploy - critical issues found in validation")
            error_result = DeploymentResult(
                deployment_id="validation-failed",
                status=DeploymentStatus.FAILED,
                subscription_id=settings.azure_deployment.subscription_id,
                resource_group=settings.azure_deployment.resource_group,
                location=settings.azure_deployment.location,
                error_message="Deployment blocked due to critical validation issues",
                error_details={"validation_issues": len(validation_result.issues)},
            )
            await ctx.yield_output(error_result)
            return

        # Log warning if there are errors but no critical issues
        if validation_result.has_errors and settings.workflow.require_review_approval:
            logger.warning(
                f"Deployment has {validation_result.issue_summary.get('error', 0)} errors - "
                f"proceeding with deployment (review approval required in production)"
            )

        # In a real workflow, BicepCode would be passed via shared state
        # For this demo, we'll need to retrieve it from context or workflow state
        # For now, we'll create a deployment using the validated bicep code
        
        try:
            # Step 1: Get Bicep code from validation context (would come from workflow state)
            bicep_code = await self._get_bicep_code_from_context(ctx, validation_result)

            # Step 2: Deploy to Azure
            deployment_result = await self._deploy_to_azure(bicep_code, validation_result)

            logger.info(f"Deployment {deployment_result.status.value}: {deployment_result.deployment_id}")

            # Step 3: Yield final output
            await ctx.yield_output(deployment_result)

        except Exception as e:
            logger.error(f"Deployment failed with exception: {e}", exc_info=True)
            error_result = DeploymentResult(
                deployment_id=f"error-{uuid.uuid4().hex[:8]}",
                status=DeploymentStatus.FAILED,
                subscription_id=settings.azure_deployment.subscription_id,
                resource_group=settings.azure_deployment.resource_group,
                location=settings.azure_deployment.location,
                error_message=str(e),
                deployment_logs=[f"Exception during deployment: {e}"],
            )
            await ctx.yield_output(error_result)

    async def _get_bicep_code_from_context(
        self, ctx: WorkflowContext, validation_result: ValidationResult
    ) -> BicepCode:
        """
        Retrieve Bicep code from workflow context/state.
        
        In a real implementation, this would access shared workflow state.
        For this demo, we'll use the corrected code from validation if available.
        """
        # This is a simplified placeholder - in real workflow, would access shared state
        # For now, create a minimal BicepCode object
        bicep_code_str = validation_result.corrected_bicep_code or "// Bicep code placeholder"

        return BicepCode(
            source_specification=validation_result.bicep_source,
            parameters=[],
            variables=[],
            resources=[],
            outputs=[],
            bicep_code=bicep_code_str,
            generation_notes=["Retrieved from validation context"],
        )

    async def _deploy_to_azure(
        self, bicep_code: BicepCode, validation_result: ValidationResult
    ) -> DeploymentResult:
        """Deploy Bicep template to Azure."""
        deployment_id = f"deploy-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        started_at = datetime.utcnow()

        logger.info(f"Starting Azure deployment: {deployment_id}")

        deployment_result = DeploymentResult(
            deployment_id=deployment_id,
            started_at=started_at,
            status=DeploymentStatus.PENDING,
            subscription_id=settings.azure_deployment.subscription_id,
            resource_group=settings.azure_deployment.resource_group,
            location=settings.azure_deployment.location,
            deployment_logs=[],
        )

        try:
            # Step 1: Compile Bicep to ARM JSON
            deployment_result.deployment_logs.append("Compiling Bicep to ARM JSON...")
            deployment_result.status = DeploymentStatus.VALIDATING
            
            arm_template = await self._compile_bicep_to_arm(bicep_code.bicep_code)

            # Step 2: Create Azure deployment
            deployment_result.deployment_logs.append("Creating Azure deployment...")
            deployment_result.status = DeploymentStatus.RUNNING

            async with DefaultAzureCredential() as credential:
                async with ResourceManagementClient(
                    credential=credential,
                    subscription_id=settings.azure_deployment.subscription_id,
                ) as client:
                    # Ensure resource group exists
                    await self._ensure_resource_group(client, deployment_result)

                    # Create deployment
                    deployment_properties = DeploymentProperties(
                        template=arm_template,
                        mode=DeploymentMode.INCREMENTAL,
                        parameters={},  # Would include parameter values here
                    )

                    deployment = Deployment(properties=deployment_properties)

                    logger.info(f"Submitting deployment to resource group: {deployment_result.resource_group}")

                    # Start deployment (async operation)
                    deployment_operation = await client.deployments.begin_create_or_update(
                        resource_group_name=deployment_result.resource_group,
                        deployment_name=deployment_id,
                        parameters=deployment,
                    )

                    # Wait for deployment to complete
                    deployment_result.deployment_logs.append("Waiting for deployment to complete...")
                    result = await deployment_operation.result()

                    # Step 3: Collect deployment info
                    deployment_result.status = DeploymentStatus.SUCCEEDED
                    deployment_result.completed_at = datetime.utcnow()

                    # Get deployed resources
                    if result.properties and result.properties.output_resources:
                        for resource in result.properties.output_resources:
                            deployed_resource = DeployedResource(
                                resource_name=resource.id.split('/')[-1],
                                resource_type=resource.id.split('/')[6] + '/' + resource.id.split('/')[7],
                                resource_id=resource.id,
                                status="Deployed",
                                provisioning_state="Succeeded",
                            )
                            deployment_result.deployed_resources.append(deployed_resource)

                    # Get outputs
                    if result.properties and result.properties.outputs:
                        deployment_result.deployment_outputs = result.properties.outputs

                    deployment_result.total_resources = len(deployment_result.deployed_resources)
                    deployment_result.successful_resources = len(deployment_result.deployed_resources)

                    deployment_result.deployment_logs.append(
                        f"Deployment completed successfully: {deployment_result.total_resources} resources deployed"
                    )

                    logger.info(f"Deployment succeeded: {deployment_result.deployment_id}")

        except Exception as e:
            logger.error(f"Deployment failed: {e}", exc_info=True)
            deployment_result.status = DeploymentStatus.FAILED
            deployment_result.completed_at = datetime.utcnow()
            deployment_result.error_message = str(e)
            deployment_result.error_details = {"exception_type": type(e).__name__}
            deployment_result.deployment_logs.append(f"Deployment failed: {e}")

            # Try to get error analysis from AI agent if available
            if self.agent:
                try:
                    error_analysis = await self._analyze_deployment_error(str(e))
                    deployment_result.deployment_logs.append(f"Error analysis: {error_analysis}")
                except Exception as analysis_error:
                    logger.warning(f"Could not analyze error: {analysis_error}")

        return deployment_result

    async def _compile_bicep_to_arm(self, bicep_code: str) -> dict:
        """
        Compile Bicep to ARM JSON template.

        Uses Azure CLI: az bicep build
        """
        logger.info("Compiling Bicep to ARM JSON")

        try:
            # Write Bicep to temp file
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.bicep', delete=False, encoding='utf-8'
            ) as f:
                f.write(bicep_code)
                bicep_file = Path(f.name)

            # Compile using az bicep build
            process = await asyncio.create_subprocess_exec(
                'az', 'bicep', 'build',
                '--file', str(bicep_file),
                '--stdout',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            # Clean up
            bicep_file.unlink()

            if process.returncode == 0:
                # Parse ARM JSON from stdout
                arm_template = json.loads(stdout.decode('utf-8'))
                logger.info("Bicep compiled successfully")
                return arm_template
            else:
                error_msg = stderr.decode('utf-8')
                raise RuntimeError(f"Bicep compilation failed: {error_msg}")

        except FileNotFoundError:
            raise RuntimeError("Azure CLI not found - required for Bicep compilation")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse ARM template JSON: {e}")

    async def _ensure_resource_group(
        self, client: ResourceManagementClient, deployment_result: DeploymentResult
    ) -> None:
        """Ensure the target resource group exists."""
        logger.info(f"Checking resource group: {deployment_result.resource_group}")

        try:
            exists = await client.resource_groups.check_existence(
                deployment_result.resource_group
            )

            if not exists:
                logger.info(f"Creating resource group: {deployment_result.resource_group}")
                await client.resource_groups.create_or_update(
                    deployment_result.resource_group,
                    {"location": deployment_result.location},
                )
                deployment_result.deployment_logs.append(
                    f"Created resource group: {deployment_result.resource_group}"
                )
            else:
                logger.info(f"Resource group exists: {deployment_result.resource_group}")

        except Exception as e:
            logger.error(f"Error checking/creating resource group: {e}")
            raise

    async def _analyze_deployment_error(self, error_message: str) -> str:
        """Use AI agent to analyze deployment error and suggest remediation."""
        if not self.agent:
            return "AI analysis not available"

        prompt = f"""Analyze this Azure deployment error and provide remediation steps:

Error: {error_message}

Provide:
1. Root cause
2. Specific remediation steps
3. Prevention recommendations
"""

        response = await self.agent.run([{"role": "user", "content": prompt}])
        return response.text


def create_iac_deployment_agent(
    chat_client: Optional[AzureAIAgentClient] = None,
) -> IaCDeploymentAgent:
    """Factory function to create an IaCDeploymentAgent instance."""
    return IaCDeploymentAgent(chat_client)


async def create_iac_deployment_agent_with_client() -> IaCDeploymentAgent:
    """Create agent with a new AI client."""
    async with DefaultAzureCredential() as credential:
        chat_client = AzureAIAgentClient(
            project_endpoint=settings.azure_ai.project_endpoint,
            model_deployment_name=settings.azure_ai.model_deployment_name,
            async_credential=credential,
            agent_name="IaCDeploymentAgent",
        )
        return create_iac_deployment_agent(chat_client)
