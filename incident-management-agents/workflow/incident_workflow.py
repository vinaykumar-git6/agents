"""
Main Incident Management Workflow
Orchestrates all agents in the incident remediation process.
"""
import logging
import asyncio
from agent_framework import WorkflowBuilder, WorkflowRunState, WorkflowOutputEvent, WorkflowStatusEvent
from azure.identity.aio import DefaultAzureCredential
from agents.incident_analysis_agent import create_incident_analysis_agent
from agents.remediation_planning_agent import create_remediation_planning_agent
from agents.human_approval_executor import create_human_approval_executor
from agents.remediation_execution_agent import create_remediation_execution_agent
from agents.servicenow_update_agent import create_servicenow_update_agent
from models import ServiceNowIncident, IncidentStatus
from utils.cosmos_client import cosmos_service
from config import config
import uuid

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class IncidentManagementWorkflow:
    """
    Main workflow orchestrator for automated incident management.
    
    Workflow stages:
    1. Incident Analysis Agent - Analyzes and summarizes incident
    2. Remediation Planning Agent - Creates remediation plan from KB
    3. Human Approval Executor - Gets human approval for plan
    4. Remediation Execution Agent - Executes approved plan via Azure Functions
    5. ServiceNow Update Agent - Updates incident with RCA and resolution
    """
    
    def __init__(self):
        """Initialize the incident management workflow."""
        self.workflow = None
        self.credential = None
        logger.info("Incident Management Workflow initialized")
    
    async def build_workflow(self):
        """
        Build the multi-agent workflow using Microsoft Agent Framework.
        
        This creates the directed graph of agents and their connections.
        """
        try:
            logger.info("Building incident management workflow...")
            
            # Initialize Azure credential
            self.credential = DefaultAzureCredential()
            
            # Create all agents
            incident_analysis_agent = await create_incident_analysis_agent(self.credential)
            remediation_planning_agent = await create_remediation_planning_agent(self.credential)
            human_approval_executor = create_human_approval_executor()
            remediation_execution_agent = create_remediation_execution_agent()
            servicenow_update_agent = await create_servicenow_update_agent(self.credential)
            
            # Build workflow using fluent API
            # The workflow is a sequential pipeline with human-in-the-loop
            self.workflow = (
                WorkflowBuilder()
                .set_start_executor(incident_analysis_agent)
                .add_edge(incident_analysis_agent, remediation_planning_agent)
                .add_edge(remediation_planning_agent, human_approval_executor)
                .add_edge(human_approval_executor, remediation_execution_agent)
                .add_edge(remediation_execution_agent, servicenow_update_agent)
                .build()
            )
            
            logger.info("Workflow built successfully")
            logger.info(
                "Workflow stages: "
                "Analysis → Planning → Approval → Execution → ServiceNow Update"
            )
            
            return self.workflow
            
        except Exception as e:
            logger.error(f"Failed to build workflow: {str(e)}", exc_info=True)
            raise
    
    async def process_incident(self, incident_data: dict) -> None:
        """
        Process a ServiceNow incident through the complete workflow.
        
        Args:
            incident_data: ServiceNow incident data from webhook
        """
        workflow_id = str(uuid.uuid4())
        
        try:
            logger.info("=" * 80)
            logger.info(f"Starting workflow execution for incident: {incident_data.get('number')}")
            logger.info(f"Workflow ID: {workflow_id}")
            logger.info("=" * 80)
            
            # Validate incident data
            incident = ServiceNowIncident(**incident_data)
            
            # Initialize workflow state in Cosmos DB
            workflow_state = {
                "workflow_id": workflow_id,
                "incident_id": incident.sys_id,
                "incident_number": incident.number,
                "current_status": IncidentStatus.ANALYZING.value,
                "incident_data": incident.dict(),
                "created_at": incident.opened_at.isoformat(),
                "updated_at": incident.opened_at.isoformat()
            }
            cosmos_service.save_workflow_state(workflow_state)
            
            # Ensure workflow is built
            if not self.workflow:
                await self.build_workflow()
            
            # Run workflow with streaming to observe progress
            logger.info(f"Starting workflow execution for {incident.number}")
            
            async for event in self.workflow.run_stream(incident.dict()):
                # Handle different event types
                if isinstance(event, WorkflowStatusEvent):
                    await self._handle_status_event(event, workflow_id)
                    
                elif isinstance(event, WorkflowOutputEvent):
                    await self._handle_output_event(event, workflow_id)
                    
                else:
                    # Log other events for debugging
                    logger.debug(f"Event: {event.__class__.__name__}: {event}")
            
            logger.info("=" * 80)
            logger.info(f"Workflow execution completed for incident: {incident.number}")
            logger.info(f"Workflow ID: {workflow_id}")
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error(
                f"Error processing incident {incident_data.get('number')}: {str(e)}", 
                exc_info=True
            )
            
            # Update workflow state to failed
            try:
                workflow_state = cosmos_service.get_workflow_state(workflow_id)
                if workflow_state:
                    workflow_state["current_status"] = IncidentStatus.FAILED.value
                    workflow_state["error_message"] = str(e)
                    cosmos_service.save_workflow_state(workflow_state)
            except:
                pass  # Don't fail the error handler
            
            raise
    
    async def _handle_status_event(self, event: WorkflowStatusEvent, workflow_id: str):
        """Handle workflow status change events."""
        status_map = {
            WorkflowRunState.IN_PROGRESS: "⚙️  IN PROGRESS",
            WorkflowRunState.IN_PROGRESS_PENDING_REQUESTS: "⏸️  PENDING REQUESTS",
            WorkflowRunState.IDLE: "✅ IDLE",
            WorkflowRunState.IDLE_WITH_PENDING_REQUESTS: "⏸️  IDLE - AWAITING INPUT",
        }
        
        status_str = status_map.get(event.state, str(event.state))
        logger.info(f"Workflow Status: {status_str} (Origin: {event.origin.value})")
        
        # Update workflow state in database
        if event.state == WorkflowRunState.IN_PROGRESS_PENDING_REQUESTS:
            # This typically means waiting for human approval
            try:
                workflow_state = cosmos_service.get_workflow_state(workflow_id)
                if workflow_state:
                    workflow_state["current_status"] = IncidentStatus.PENDING_APPROVAL.value
                    cosmos_service.save_workflow_state(workflow_state)
            except Exception as e:
                logger.error(f"Failed to update workflow state: {str(e)}")
    
    async def _handle_output_event(self, event: WorkflowOutputEvent, workflow_id: str):
        """Handle workflow output events (final results)."""
        logger.info(f"📊 Workflow Output Received:")
        logger.info(f"   Type: {type(event.data).__name__}")
        
        if hasattr(event.data, 'dict'):
            output_data = event.data.dict()
            logger.info(f"   Data: {output_data}")
            
            # Update workflow state with final output
            try:
                workflow_state = cosmos_service.get_workflow_state(workflow_id)
                if workflow_state:
                    workflow_state["current_status"] = IncidentStatus.RESOLVED.value
                    workflow_state["resolution"] = output_data
                    cosmos_service.save_workflow_state(workflow_state)
            except Exception as e:
                logger.error(f"Failed to update workflow state with output: {str(e)}")
        else:
            logger.info(f"   Data: {event.data}")
    
    async def cleanup(self):
        """Clean up workflow resources."""
        logger.info("Cleaning up workflow resources...")
        if self.credential:
            await self.credential.close()
        logger.info("Workflow cleanup complete")


# Global workflow instance
_workflow_instance = None


async def get_workflow() -> IncidentManagementWorkflow:
    """
    Get or create the global workflow instance.
    
    Returns:
        IncidentManagementWorkflow instance
    """
    global _workflow_instance
    if _workflow_instance is None:
        _workflow_instance = IncidentManagementWorkflow()
        await _workflow_instance.build_workflow()
    return _workflow_instance


async def process_incident_webhook(incident_data: dict) -> None:
    """
    Process an incident webhook from ServiceNow.
    
    This is the main entry point for incident processing.
    
    Args:
        incident_data: ServiceNow incident data
    """
    workflow = await get_workflow()
    await workflow.process_incident(incident_data)


# Example usage and testing
async def test_workflow():
    """Test the workflow with a sample incident."""
    
    # Sample ServiceNow incident
    sample_incident = {
        "sys_id": "test_" + str(uuid.uuid4()),
        "number": "INC0012345",
        "short_description": "Application server not responding",
        "description": "Users are unable to access the customer portal. The application server appears to be unresponsive. Multiple users have reported seeing timeout errors when trying to login.",
        "priority": "2",
        "urgency": "2",
        "impact": "2",
        "category": "Infrastructure",
        "subcategory": "Server",
        "configuration_item": "PROD-APP-SERVER-01",
        "state": "2",
        "opened_at": "2025-11-14T10:30:00Z",
        "assigned_to": "IT Operations",
        "additional_comments": "Server monitoring shows high memory usage and slow response times."
    }
    
    logger.info("Starting test workflow execution...")
    
    try:
        await process_incident_webhook(sample_incident)
        logger.info("Test workflow completed successfully!")
        
    except Exception as e:
        logger.error(f"Test workflow failed: {str(e)}", exc_info=True)


if __name__ == "__main__":
    # Run test workflow
    asyncio.run(test_workflow())
