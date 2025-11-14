"""
Remediation Execution Agent
Executes approved remediation plans by invoking Azure Functions.
"""
import logging
import httpx
import json
from datetime import datetime
from typing import Never
from agent_framework import Executor, WorkflowContext, handler
from models import RemediationPlan, RemediationExecution, RemediationResult
from utils.cosmos_client import cosmos_service
from utils.email_service import email_service
from config import config
import uuid

logger = logging.getLogger(__name__)


class RemediationExecutionAgent(Executor):
    """
    Agent that executes approved remediation plans.
    
    This agent:
    1. Receives approved remediation plan
    2. Executes each action by invoking Azure Functions
    3. Tracks execution status and results
    4. Sends summary email with all actions performed
    5. Forwards results to ServiceNow update agent
    """
    
    def __init__(self, agent_id: str = "remediation_execution_agent"):
        """
        Initialize the Remediation Execution Agent.
        
        Args:
            agent_id: Unique identifier for this agent
        """
        super().__init__(id=agent_id)
        self.http_client = httpx.AsyncClient(timeout=300.0)  # 5 minute timeout
        logger.info(f"Remediation Execution Agent initialized: {agent_id}")
    
    @handler
    async def execute_plan(
        self, 
        remediation_plan: RemediationPlan, 
        ctx: WorkflowContext[RemediationExecution]
    ) -> None:
        """
        Execute the approved remediation plan.
        
        Args:
            remediation_plan: Approved remediation plan
            ctx: Workflow context to send execution results to ServiceNow agent
        """
        try:
            execution_id = str(uuid.uuid4())
            logger.info(
                f"Starting execution of remediation plan {remediation_plan.plan_id} "
                f"(execution ID: {execution_id})"
            )
            
            # Initialize execution tracking
            execution = RemediationExecution(
                execution_id=execution_id,
                incident_id=remediation_plan.incident_id,
                plan_id=remediation_plan.plan_id,
                approval_id="",  # Would be set from context in real implementation
                results=[],
                overall_status="in_progress",
                started_at=datetime.utcnow()
            )
            
            # Execute each action in sequence
            for i, action in enumerate(remediation_plan.actions, 1):
                logger.info(
                    f"Executing action {i}/{len(remediation_plan.actions)}: "
                    f"{action.action_type} on {action.target_resource}"
                )
                
                action_result = await self._execute_action(action)
                execution.results.append(action_result)
                
                # Stop execution if action failed and it's critical
                if action_result.status == "failed" and action.risk_level == "HIGH":
                    logger.error(
                        f"Critical action failed: {action.action_id}. "
                        "Stopping execution."
                    )
                    execution.overall_status = "failed"
                    break
            
            # Determine overall status
            if execution.overall_status != "failed":
                failed_actions = [r for r in execution.results if r.status == "failed"]
                if not failed_actions:
                    execution.overall_status = "success"
                elif len(failed_actions) < len(execution.results):
                    execution.overall_status = "partial_success"
                else:
                    execution.overall_status = "failed"
            
            execution.completed_at = datetime.utcnow()
            
            logger.info(
                f"Execution completed: {execution.overall_status}. "
                f"{len([r for r in execution.results if r.status == 'success'])}/{len(execution.results)} "
                "actions succeeded."
            )
            
            # Save execution to Cosmos DB
            cosmos_service.save_workflow_state({
                "workflow_id": execution_id,
                "incident_id": execution.incident_id,
                "execution": execution.dict()
            })
            
            # Send summary email
            await self._send_execution_summary_email(remediation_plan, execution)
            
            # Send execution results to next agent (ServiceNow update)
            await ctx.send_message(execution)
            
        except Exception as e:
            logger.error(f"Error executing remediation plan: {str(e)}", exc_info=True)
            raise
    
    async def _execute_action(self, action) -> RemediationResult:
        """
        Execute a single remediation action by calling Azure Functions.
        
        Args:
            action: RemediationAction to execute
            
        Returns:
            RemediationResult with execution outcome
        """
        start_time = datetime.utcnow()
        
        try:
            # Prepare request to Azure Functions
            function_url = f"{config.azure_functions.remediation_url}/api/remediation"
            
            headers = {
                "Content-Type": "application/json",
                "x-functions-key": config.azure_functions.function_key or ""
            }
            
            payload = {
                "action_id": action.action_id,
                "action_type": action.action_type,
                "target_resource": action.target_resource,
                "parameters": action.parameters
            }
            
            logger.info(f"Calling Azure Function: {function_url}")
            logger.debug(f"Payload: {json.dumps(payload, indent=2)}")
            
            # Execute the function
            response = await self.http_client.post(
                function_url,
                json=payload,
                headers=headers
            )
            
            end_time = datetime.utcnow()
            
            if response.status_code == 200:
                result_data = response.json()
                logger.info(f"Action {action.action_id} completed successfully")
                
                return RemediationResult(
                    action_id=action.action_id,
                    status="success",
                    start_time=start_time,
                    end_time=end_time,
                    output=result_data.get("output", "Action completed successfully"),
                    error_message=None
                )
            else:
                error_msg = f"Function returned status {response.status_code}: {response.text}"
                logger.error(f"Action {action.action_id} failed: {error_msg}")
                
                return RemediationResult(
                    action_id=action.action_id,
                    status="failed",
                    start_time=start_time,
                    end_time=end_time,
                    output=None,
                    error_message=error_msg
                )
                
        except httpx.TimeoutException:
            end_time = datetime.utcnow()
            error_msg = f"Action timed out after {(end_time - start_time).total_seconds():.0f} seconds"
            logger.error(f"Action {action.action_id} timed out")
            
            return RemediationResult(
                action_id=action.action_id,
                status="failed",
                start_time=start_time,
                end_time=end_time,
                output=None,
                error_message=error_msg
            )
            
        except Exception as e:
            end_time = datetime.utcnow()
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(f"Action {action.action_id} failed with exception: {e}", exc_info=True)
            
            return RemediationResult(
                action_id=action.action_id,
                status="failed",
                start_time=start_time,
                end_time=end_time,
                output=None,
                error_message=error_msg
            )
    
    async def _send_execution_summary_email(
        self, 
        plan: RemediationPlan, 
        execution: RemediationExecution
    ) -> None:
        """
        Send email summary of remediation execution.
        
        Args:
            plan: The remediation plan that was executed
            execution: Execution results
        """
        try:
            # Build actions summary with results
            actions_performed = []
            for result in execution.results:
                # Find corresponding action
                action = next(
                    (a for a in plan.actions if a.action_id == result.action_id),
                    None
                )
                if action:
                    duration = (result.end_time - result.start_time).total_seconds()
                    actions_performed.append({
                        "description": action.description,
                        "status": result.status,
                        "duration_seconds": duration,
                        "output": result.output,
                        "error": result.error_message
                    })
            
            # Create resolution notes
            success_count = len([r for r in execution.results if r.status == "success"])
            total_duration = (execution.completed_at - execution.started_at).total_seconds()
            
            resolution_notes = f"""
Remediation Execution Summary:
- Execution ID: {execution.execution_id}
- Actions Completed: {success_count}/{len(execution.results)}
- Total Duration: {total_duration:.1f} seconds
- Overall Status: {execution.overall_status.upper()}

Actions Performed:
"""
            for i, action_result in enumerate(actions_performed, 1):
                status_icon = "✅" if action_result["status"] == "success" else "❌"
                resolution_notes += f"\n{i}. {status_icon} {action_result['description']}"
                resolution_notes += f"\n   Duration: {action_result['duration_seconds']:.2f}s"
                if action_result.get("error"):
                    resolution_notes += f"\n   Error: {action_result['error']}"
            
            # Send email
            await email_service.send_remediation_summary_email(
                recipients=config.approval.required_emails,
                incident_number=plan.incident_id,
                incident_summary=plan.summary,
                actions_performed=actions_performed,
                overall_status=execution.overall_status,
                resolution_notes=resolution_notes
            )
            
            logger.info(f"Execution summary email sent for {execution.execution_id}")
            
        except Exception as e:
            logger.error(f"Failed to send execution summary email: {str(e)}")
            # Don't raise - email failure shouldn't stop workflow
    
    async def close(self):
        """Clean up HTTP client."""
        await self.http_client.aclose()


def create_remediation_execution_agent() -> RemediationExecutionAgent:
    """
    Factory function to create a Remediation Execution Agent.
    
    Returns:
        Configured RemediationExecutionAgent instance
    """
    return RemediationExecutionAgent()
