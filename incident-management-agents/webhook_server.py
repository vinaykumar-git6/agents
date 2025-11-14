"""
FastAPI Webhook Server
Receives ServiceNow incident webhooks and triggers the workflow.
"""
import logging
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Header
from fastapi.responses import JSONResponse
import asyncio
from typing import Optional
from workflow.incident_workflow import process_incident_webhook, get_workflow
from models import ServiceNowIncident
from utils.cosmos_client import cosmos_service
from config import config
import hmac
import hashlib

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Incident Management Agent System",
    description="Automated incident management using Microsoft Agent Framework",
    version="1.0.0"
)


def verify_webhook_signature(payload: bytes, signature: Optional[str]) -> bool:
    """
    Verify webhook signature for security.
    
    Args:
        payload: Request payload bytes
        signature: Signature from header
        
    Returns:
        True if signature is valid
    """
    if not config.webhook.secret_token:
        logger.warning("Webhook secret token not configured - skipping verification")
        return True
    
    if not signature:
        logger.warning("No signature provided in webhook request")
        return False
    
    # Calculate expected signature
    expected_signature = hmac.new(
        config.webhook.secret_token.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected_signature)


@app.on_event("startup")
async def startup_event():
    """Initialize workflow on server startup."""
    logger.info("Starting Incident Management Webhook Server...")
    logger.info(f"Server: {config.webhook.host}:{config.webhook.port}")
    
    try:
        # Pre-build workflow to reduce first-request latency
        workflow = await get_workflow()
        logger.info("Workflow pre-initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize workflow: {str(e)}", exc_info=True)


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on server shutdown."""
    logger.info("Shutting down Incident Management Webhook Server...")
    workflow = await get_workflow()
    await workflow.cleanup()


@app.get("/")
async def root():
    """Root endpoint - health check."""
    return {
        "service": "Incident Management Agent System",
        "status": "running",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "workflow": "ready",
        "cosmos_db": "connected"
    }


@app.post("/webhook/servicenow/incident")
async def servicenow_incident_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_servicenow_signature: Optional[str] = Header(None)
):
    """
    Receive incident webhooks from ServiceNow.
    
    ServiceNow should POST incident data to this endpoint when:
    - A new incident is created
    - An incident is updated with specific criteria
    
    Args:
        request: FastAPI request object
        background_tasks: Background task executor
        x_servicenow_signature: Webhook signature for verification
        
    Returns:
        Acknowledgment response
    """
    try:
        # Read raw body for signature verification
        body = await request.body()
        
        # Verify webhook signature
        if not verify_webhook_signature(body, x_servicenow_signature):
            logger.error("Invalid webhook signature")
            raise HTTPException(status_code=401, detail="Invalid signature")
        
        # Parse JSON payload
        incident_data = await request.json()
        
        logger.info(f"Received ServiceNow incident webhook: {incident_data.get('number')}")
        
        # Validate incident data
        try:
            incident = ServiceNowIncident(**incident_data)
        except Exception as e:
            logger.error(f"Invalid incident data: {str(e)}")
            raise HTTPException(status_code=400, detail=f"Invalid incident data: {str(e)}")
        
        # Process incident in background
        # This allows webhook to return immediately while workflow runs asynchronously
        background_tasks.add_task(process_incident_webhook, incident_data)
        
        logger.info(f"Incident {incident.number} queued for processing")
        
        return JSONResponse(
            status_code=202,
            content={
                "status": "accepted",
                "message": f"Incident {incident.number} queued for processing",
                "incident_id": incident.sys_id,
                "incident_number": incident.number
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/approval/{approval_id}")
async def approval_response(
    approval_id: str,
    action: str,
    approver_email: str,
    rejection_reason: Optional[str] = None
):
    """
    Handle approval/rejection responses.
    
    This endpoint is called when an approver clicks approve/reject in the email.
    
    Args:
        approval_id: The approval request ID
        action: "approve" or "reject"
        approver_email: Email of the person responding
        rejection_reason: Reason if rejected
        
    Returns:
        Confirmation response
    """
    try:
        logger.info(f"Received approval response: {action} from {approver_email} for {approval_id}")
        
        if action not in ["approve", "reject"]:
            raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")
        
        # Get workflow and human approval executor
        workflow = await get_workflow()
        
        # TODO: In production, you would:
        # 1. Retrieve the approval executor from workflow
        # 2. Call its process_approval_response method
        # 3. This would resume the paused workflow
        
        # For now, update Cosmos DB
        cosmos_service.update_approval_status(
            approval_id=approval_id,
            status="approved" if action == "approve" else "rejected",
            approved_by=approver_email,
            rejection_reason=rejection_reason
        )
        
        return {
            "status": "success",
            "message": f"Remediation plan {action}d successfully",
            "approval_id": approval_id,
            "action": action
        }
        
    except Exception as e:
        logger.error(f"Error processing approval response: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/workflow/{workflow_id}")
async def get_workflow_status(workflow_id: str):
    """
    Get workflow status by ID.
    
    Args:
        workflow_id: Workflow identifier
        
    Returns:
        Workflow state
    """
    try:
        workflow_state = cosmos_service.get_workflow_state(workflow_id)
        
        if not workflow_state:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        return workflow_state
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving workflow status: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/incident/{incident_id}")
async def get_incident_status(incident_id: str):
    """
    Get incident status by ID.
    
    Args:
        incident_id: ServiceNow incident ID
        
    Returns:
        Incident data and workflow state
    """
    try:
        incident_data = cosmos_service.get_incident(incident_id)
        
        if not incident_data:
            raise HTTPException(status_code=404, detail="Incident not found")
        
        return incident_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving incident: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host=config.webhook.host,
        port=config.webhook.port,
        log_level="info"
    )
