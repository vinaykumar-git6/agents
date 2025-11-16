"""
Main Workflow Orchestrator for Architecture Diagram to IaC Pipeline.

Orchestrates the complete 6-stage workflow:
1. Computer Vision Analysis (diagram → extracted resources)
2. Resource Analysis (extracted → synthesized specifications)
3. IaC Generation (specifications → Bicep code)
4. IaC Review (Bicep code → validation results)
5. IaC Correction (validation results → corrected Bicep code)
6. IaC Deployment (corrected code → deployed infrastructure)

Uses Microsoft Agent Framework for multi-agent orchestration.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
import uuid

from agent_framework import (
    WorkflowBuilder,
    WorkflowOutputEvent,
    WorkflowStatusEvent,
    WorkflowRunState,
    ExecutorFailedEvent,
    WorkflowFailedEvent,
)
from agent_framework_azure_ai import AzureAIAgentClient
from azure.identity.aio import DefaultAzureCredential

from config import settings
from models import (
    DiagramAnalysis,
    ResourceSpecification,
    BicepCode,
    ValidationResult,
    DeploymentResult,
    WorkflowStage,
    WorkflowState,
)
from agents import (
    create_resource_analysis_agent,
    create_iac_generation_agent,
    create_iac_review_agent,
    create_iac_correction_agent,
    create_iac_deployment_agent,
)
from utils.vision_service import get_vision_service

logger = logging.getLogger(__name__)


class ArchDiagIaCWorkflow:
    """
    Main workflow orchestrator for architecture diagram to IaC pipeline.
    
    This coordinates the entire process from diagram upload to infrastructure deployment.
    """

    def __init__(self):
        """Initialize the workflow orchestrator."""
        self.vision_service = get_vision_service()
        self.workflow = None
        self.workflow_state: Optional[WorkflowState] = None

    async def build_workflow(self) -> None:
        """Build the multi-agent workflow pipeline."""
        logger.info("Building archdiag-iac-agents workflow")

        # Create Azure AI client for agents
        async with DefaultAzureCredential() as credential:
            chat_client = AzureAIAgentClient(
                project_endpoint=settings.azure_ai.project_endpoint,
                model_deployment_name=settings.azure_ai.model_deployment_name,
                async_credential=credential,
                agent_name="ArchDiagIaCWorkflow",
            )

            # Create all agents
            resource_analysis_agent = create_resource_analysis_agent(chat_client)
            iac_generation_agent = create_iac_generation_agent(chat_client)
            iac_review_agent = create_iac_review_agent(chat_client)
            iac_correction_agent = create_iac_correction_agent(chat_client)
            iac_deployment_agent = create_iac_deployment_agent(chat_client)

            # Build workflow with sequential pipeline
            # Stage 1: Vision Analysis (handled separately, not an agent)
            # Stage 2: Resource Analysis Agent
            # Stage 3: IaC Generation Agent
            # Stage 4: IaC Review Agent
            # Stage 5: IaC Correction Agent (NEW)
            # Stage 6: IaC Deployment Agent

            self.workflow = (
                WorkflowBuilder()
                .set_start_executor(resource_analysis_agent)
                .add_edge(resource_analysis_agent, iac_generation_agent)
                .add_edge(iac_generation_agent, iac_review_agent)
                .add_edge(iac_review_agent, iac_correction_agent)
                .add_edge(iac_correction_agent, iac_deployment_agent)
                .build()
            )

            logger.info("Workflow built successfully")

    async def process_diagram(
        self,
        image_path: str | Path,
        resource_group: Optional[str] = None,
        location: Optional[str] = None,
    ) -> WorkflowState:
        """
        Process an architecture diagram through the complete workflow.

        Args:
            image_path: Path to architecture diagram image
            resource_group: Target resource group (optional, uses default if not provided)
            location: Target Azure region (optional, uses default if not provided)

        Returns:
            WorkflowState: Complete workflow execution state
        """
        workflow_id = f"workflow-{uuid.uuid4().hex[:8]}"
        logger.info(f"Starting workflow {workflow_id} for diagram: {image_path}")

        # Initialize workflow state
        self.workflow_state = WorkflowState(
            workflow_id=workflow_id,
            source_image=str(image_path),
            current_stage=WorkflowStage.VISION_ANALYSIS,
        )

        try:
            # Stage 1: Computer Vision Analysis
            logger.info("Stage 1: Analyzing diagram with Computer Vision")
            self.workflow_state.current_stage = WorkflowStage.VISION_ANALYSIS

            diagram_analysis = await self.vision_service.analyze_diagram(image_path)
            self.workflow_state.diagram_analysis = diagram_analysis

            logger.info(
                f"Diagram analysis complete: {len(diagram_analysis.resources)} resources detected"
            )

            # Ensure workflow is built
            if not self.workflow:
                await self.build_workflow()

            # Stage 2-5: Run multi-agent workflow
            logger.info("Starting multi-agent workflow")
            self.workflow_state.current_stage = WorkflowStage.RESOURCE_ANALYSIS

            # Run workflow with streaming to monitor progress
            async for event in self.workflow.run_stream(diagram_analysis):
                await self._handle_workflow_event(event)

            # Mark workflow as completed
            self.workflow_state.is_completed = True
            self.workflow_state.completed_at = datetime.utcnow()
            self.workflow_state.current_stage = WorkflowStage.COMPLETED

            logger.info(f"Workflow {workflow_id} completed successfully")

        except Exception as e:
            logger.error(f"Workflow {workflow_id} failed: {e}", exc_info=True)
            self.workflow_state.has_errors = True
            self.workflow_state.error_message = str(e)
            self.workflow_state.current_stage = WorkflowStage.FAILED
            self.workflow_state.completed_at = datetime.utcnow()

        return self.workflow_state

    async def _handle_workflow_event(self, event) -> None:
        """Handle events from the workflow execution."""
        if isinstance(event, WorkflowStatusEvent):
            if event.state == WorkflowRunState.IN_PROGRESS:
                logger.info(f"Workflow status: IN_PROGRESS")
            elif event.state == WorkflowRunState.IDLE:
                logger.info(f"Workflow status: IDLE (completed)")

        elif isinstance(event, WorkflowOutputEvent):
            logger.info(f"Workflow output received from {event.origin.value}")

            # Determine which agent produced this output and update state
            output_data = event.data

            if isinstance(output_data, ResourceSpecification):
                logger.info("Received ResourceSpecification")
                self.workflow_state.resource_specification = output_data
                self.workflow_state.current_stage = WorkflowStage.IAC_GENERATION

            elif isinstance(output_data, BicepCode) and not hasattr(output_data, 'corrections_applied'):
                # Original BicepCode (not corrected)
                logger.info("Received BicepCode")
                self.workflow_state.bicep_code = output_data
                self.workflow_state.current_stage = WorkflowStage.IAC_REVIEW

            elif isinstance(output_data, ValidationResult):
                logger.info("Received ValidationResult")
                self.workflow_state.validation_result = output_data
                self.workflow_state.current_stage = WorkflowStage.IAC_CORRECTION

            elif hasattr(output_data, 'corrections_applied'):
                # CorrectedBicepCode
                logger.info("Received CorrectedBicepCode")
                self.workflow_state.corrected_bicep_code = output_data
                self.workflow_state.current_stage = WorkflowStage.DEPLOYMENT

            elif isinstance(output_data, DeploymentResult):
                logger.info("Received DeploymentResult")
                self.workflow_state.deployment_result = output_data
                self.workflow_state.current_stage = WorkflowStage.COMPLETED

        elif isinstance(event, ExecutorFailedEvent):
            logger.error(
                f"Executor failed: {event.executor_id} - "
                f"{event.details.error_type}: {event.details.message}"
            )
            self.workflow_state.has_errors = True
            self.workflow_state.error_message = f"{event.executor_id}: {event.details.message}"

        elif isinstance(event, WorkflowFailedEvent):
            logger.error(
                f"Workflow failed: {event.details.error_type}: {event.details.message}"
            )
            self.workflow_state.has_errors = True
            self.workflow_state.error_message = event.details.message


async def run_workflow(
    image_path: str | Path,
    resource_group: Optional[str] = None,
    location: Optional[str] = None,
) -> WorkflowState:
    """
    Convenience function to run the complete workflow.

    Args:
        image_path: Path to architecture diagram
        resource_group: Target resource group
        location: Target Azure region

    Returns:
        WorkflowState: Final workflow state
    """
    workflow = ArchDiagIaCWorkflow()
    return await workflow.process_diagram(image_path, resource_group, location)


async def test_workflow():
    """Test the workflow with a sample diagram."""
    logger.info("Running workflow test")

    # This would need a real diagram image
    # For demo purposes, you would provide a path to a diagram
    test_image = Path("samples/architecture-diagram.png")

    if not test_image.exists():
        logger.error(f"Test image not found: {test_image}")
        logger.info("Please provide a valid architecture diagram for testing")
        return

    result = await run_workflow(
        image_path=test_image,
        resource_group="rg-test-archdiag",
        location="eastus",
    )

    logger.info(f"Workflow completed: {result.workflow_id}")
    logger.info(f"Final stage: {result.current_stage.value}")
    logger.info(f"Has errors: {result.has_errors}")

    if result.deployment_result:
        logger.info(f"Deployment status: {result.deployment_result.status.value}")
        logger.info(f"Resources deployed: {result.deployment_result.total_resources}")

    return result


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Run test
    asyncio.run(test_workflow())
