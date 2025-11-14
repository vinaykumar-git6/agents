"""
Human-in-the-Loop Approval Executor
Handles approval requests for remediation plans before execution.
"""
import logging
import uuid
from datetime import datetime, timedelta
from typing import Union
from agent_framework import Executor, WorkflowContext, handler
from models import RemediationPlan, ApprovalRequest, ApprovalStatus
from utils.cosmos_client import cosmos_service
from utils.email_service import email_service
from config import config

logger = logging.getLogger(__name__)


class HumanApprovalExecutor(Executor):
    """
    Executor that requests human approval before proceeding with remediation.
    
    This executor:
    1. Creates an approval request in Cosmos DB
    2. Sends email notifications to designated approvers
    3. Waits for approval/rejection (handled by webhook)
    4. Forwards approved plans to execution agent
    """
    
    def __init__(self, executor_id: str = "human_approval_executor"):
        """
        Initialize the Human Approval Executor.
        
        Args:
            executor_id: Unique identifier for this executor
        """
        super().__init__(id=executor_id)
        logger.info(f"Human Approval Executor initialized: {executor_id}")
    
    @handler
    async def request_approval(
        self, 
        remediation_plan: RemediationPlan, 
        ctx: WorkflowContext[RemediationPlan]
    ) -> None:
        """
        Request human approval for the remediation plan.
        
        This method creates an approval request and sends notifications.
        The workflow will pause here until approval is received via webhook.
        
        Args:
            remediation_plan: The remediation plan requiring approval
            ctx: Workflow context to send approved plan to execution agent
        """
        try:
            logger.info(
                f"Requesting approval for remediation plan {remediation_plan.plan_id} "
                f"(incident: {remediation_plan.incident_id})"
            )
            
            # Create approval request
            approval_id = str(uuid.uuid4())
            expires_at = datetime.utcnow() + timedelta(minutes=config.approval.timeout_minutes)
            
            approval_request = ApprovalRequest(
                approval_id=approval_id,
                incident_id=remediation_plan.incident_id,
                plan_id=remediation_plan.plan_id,
                remediation_plan=remediation_plan,
                requested_at=datetime.utcnow(),
                expires_at=expires_at,
                status=ApprovalStatus.PENDING
            )
            
            # Save approval request to Cosmos DB
            cosmos_service.save_approval_request(approval_request.dict())
            
            # Format plan for email
            plan_text = f"""
Plan ID: {remediation_plan.plan_id}
Confidence Score: {remediation_plan.confidence_score:.0%}
Estimated Duration: {remediation_plan.estimated_total_duration_minutes} minutes

Actions to be Performed:
"""
            for i, action in enumerate(remediation_plan.actions, 1):
                plan_text += f"\n{i}. {action.description}"
                plan_text += f"\n   Type: {action.action_type}"
                plan_text += f"\n   Target: {action.target_resource}"
                plan_text += f"\n   Risk Level: {action.risk_level}"
                plan_text += f"\n   Duration: ~{action.estimated_duration_minutes} min"
                if action.parameters:
                    plan_text += f"\n   Parameters: {action.parameters}"
                plan_text += "\n"
            
            # Generate approval URL (this would be your approval API endpoint)
            # In production, this would be a proper web endpoint
            approval_url = f"{config.webhook.host}:{config.webhook.port}/api/approval/{approval_id}"
            
            # Send approval request email
            success = await email_service.send_approval_request_email(
                recipients=config.approval.required_emails,
                incident_number=remediation_plan.incident_id,
                incident_summary=remediation_plan.summary,
                remediation_plan=plan_text,
                approval_url=approval_url
            )
            
            if success:
                logger.info(
                    f"Approval request sent successfully for {remediation_plan.plan_id}. "
                    f"Waiting for approval..."
                )
            else:
                logger.warning(
                    f"Failed to send approval email, but request is stored in database"
                )
            
            # Note: The workflow will pause here. 
            # When approval is received via webhook, the orchestrator will call
            # process_approval_response() which will trigger ctx.send_message()
            
            # Store context reference for later use
            self._pending_contexts = getattr(self, '_pending_contexts', {})
            self._pending_contexts[approval_id] = (remediation_plan, ctx)
            
        except Exception as e:
            logger.error(f"Error requesting approval: {str(e)}", exc_info=True)
            raise
    
    async def process_approval_response(
        self, 
        approval_id: str, 
        approved: bool,
        approver_email: str,
        rejection_reason: str = None
    ) -> None:
        """
        Process approval response received via webhook.
        
        This method is called by the webhook handler when approval/rejection is received.
        
        Args:
            approval_id: The approval request ID
            approved: True if approved, False if rejected
            approver_email: Email of the person who approved/rejected
            rejection_reason: Reason for rejection (if applicable)
        """
        try:
            # Retrieve approval request
            approval_data = cosmos_service.get_approval_request(approval_id)
            if not approval_data:
                logger.error(f"Approval request not found: {approval_id}")
                return
            
            # Update approval status
            new_status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
            cosmos_service.update_approval_status(
                approval_id=approval_id,
                status=new_status.value,
                approved_by=approver_email,
                rejection_reason=rejection_reason
            )
            
            if approved:
                logger.info(
                    f"Remediation plan {approval_data['plan_id']} APPROVED "
                    f"by {approver_email}"
                )
                
                # Retrieve stored context and send plan to execution agent
                if hasattr(self, '_pending_contexts') and approval_id in self._pending_contexts:
                    remediation_plan, ctx = self._pending_contexts[approval_id]
                    await ctx.send_message(remediation_plan)
                    del self._pending_contexts[approval_id]
                else:
                    logger.warning(
                        f"Context not found for approved plan {approval_data['plan_id']}. "
                        "Manual execution may be required."
                    )
            else:
                logger.info(
                    f"Remediation plan {approval_data['plan_id']} REJECTED "
                    f"by {approver_email}. Reason: {rejection_reason}"
                )
                # Workflow will not proceed - incident requires manual intervention
                
        except Exception as e:
            logger.error(f"Error processing approval response: {str(e)}", exc_info=True)
            raise


def create_human_approval_executor() -> HumanApprovalExecutor:
    """
    Factory function to create a Human Approval Executor.
    
    Returns:
        Configured HumanApprovalExecutor instance
    """
    return HumanApprovalExecutor()
