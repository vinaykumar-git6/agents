"""
FastAPI Server for Architecture Diagram to IaC Pipeline.

Provides REST API endpoints for:
- Uploading architecture diagrams
- Starting workflow processing
- Checking workflow status
- Retrieving workflow results
- Downloading generated Bicep code
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
import uuid

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import aiofiles

from config import settings
from models import WorkflowState, WorkflowStage, DeploymentStatus
from workflow import run_workflow

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.monitoring.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="ArchDiag IaC Agents API",
    description="Architecture Diagram to Infrastructure as Code using AI Agents",
    version="1.0.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage for workflow states (use database in production)
workflow_states: dict[str, WorkflowState] = {}

# Upload directory
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "ArchDiag IaC Agents API",
        "version": "1.1.0",
        "description": "AI-powered architecture diagram to infrastructure as code pipeline with auto-correction",
        "endpoints": {
            "upload": "POST /api/diagram/upload",
            "status": "GET /api/workflow/{workflow_id}",
            "bicep": "GET /api/workflow/{workflow_id}/bicep",
            "corrected_bicep": "GET /api/workflow/{workflow_id}/corrected-bicep",
            "results": "GET /api/workflow/{workflow_id}/results",
            "health": "GET /health",
        },
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
    }


@app.post("/api/diagram/upload")
async def upload_diagram(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    resource_group: Optional[str] = Query(None, description="Target resource group"),
    location: Optional[str] = Query(None, description="Azure region"),
    auto_deploy: bool = Query(False, description="Auto-deploy after validation"),
):
    """
    Upload an architecture diagram and start the IaC workflow.

    Args:
        file: Architecture diagram image file
        resource_group: Target Azure resource group (optional)
        location: Target Azure region (optional)
        auto_deploy: Whether to automatically deploy after validation

    Returns:
        Workflow ID and initial status
    """
    logger.info(f"Received diagram upload: {file.filename}")

    # Validate file type
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.api.allowed_image_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {settings.api.allowed_image_extensions}",
        )

    # Check file size
    contents = await file.read()
    file_size_mb = len(contents) / (1024 * 1024)
    if file_size_mb > settings.api.max_upload_size_mb:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Max size: {settings.api.max_upload_size_mb}MB",
        )

    # Save file
    workflow_id = f"workflow-{uuid.uuid4().hex[:8]}"
    file_path = UPLOAD_DIR / f"{workflow_id}_{file.filename}"

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(contents)

    logger.info(f"Saved diagram to {file_path}")

    # Initialize workflow state
    workflow_state = WorkflowState(
        workflow_id=workflow_id,
        source_image=str(file_path),
        current_stage=WorkflowStage.VISION_ANALYSIS,
    )
    workflow_states[workflow_id] = workflow_state

    # Start workflow in background
    background_tasks.add_task(
        process_diagram_workflow,
        workflow_id,
        file_path,
        resource_group,
        location,
    )

    return JSONResponse(
        status_code=202,
        content={
            "workflow_id": workflow_id,
            "status": "accepted",
            "message": "Diagram upload successful. Processing started.",
            "check_status_url": f"/api/workflow/{workflow_id}",
        },
    )


@app.get("/api/workflow/{workflow_id}")
async def get_workflow_status(workflow_id: str):
    """
    Get the current status of a workflow.

    Args:
        workflow_id: Workflow identifier

    Returns:
        Current workflow state and progress
    """
    if workflow_id not in workflow_states:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow_state = workflow_states[workflow_id]

    # Build response
    response = {
        "workflow_id": workflow_state.workflow_id,
        "status": workflow_state.current_stage.value,
        "started_at": workflow_state.started_at.isoformat(),
        "completed_at": workflow_state.completed_at.isoformat()
        if workflow_state.completed_at
        else None,
        "is_completed": workflow_state.is_completed,
        "has_errors": workflow_state.has_errors,
        "error_message": workflow_state.error_message,
    }

    # Add stage-specific information
    if workflow_state.diagram_analysis:
        response["diagram_analysis"] = {
            "resources_detected": len(workflow_state.diagram_analysis.resources),
            "confidence": workflow_state.diagram_analysis.overall_confidence,
        }

    if workflow_state.resource_specification:
        response["resource_specification"] = {
            "total_resources": workflow_state.resource_specification.total_resources,
            "resource_types": workflow_state.resource_specification.resource_types_summary,
        }

    if workflow_state.bicep_code:
        response["bicep_code"] = {
            "resources": len(workflow_state.bicep_code.resources),
            "parameters": len(workflow_state.bicep_code.parameters),
            "outputs": len(workflow_state.bicep_code.outputs),
            "download_url": f"/api/workflow/{workflow_id}/bicep",
        }

    if workflow_state.validation_result:
        response["validation_result"] = {
            "is_valid": workflow_state.validation_result.is_valid,
            "has_critical_issues": workflow_state.validation_result.has_critical_issues,
            "issue_summary": workflow_state.validation_result.issue_summary,
            "total_issues": len(workflow_state.validation_result.issues),
        }

    if workflow_state.corrected_bicep_code:
        response["corrected_bicep_code"] = {
            "corrections_applied": len(workflow_state.corrected_bicep_code.corrections_applied),
            "original_issues": workflow_state.corrected_bicep_code.original_issues_count,
            "remaining_issues": workflow_state.corrected_bicep_code.remaining_issues_count,
            "auto_fix_success": workflow_state.corrected_bicep_code.auto_fix_success,
            "download_url": f"/api/workflow/{workflow_id}/corrected-bicep",
        }

    if workflow_state.deployment_result:
        response["deployment_result"] = {
            "status": workflow_state.deployment_result.status.value,
            "total_resources": workflow_state.deployment_result.total_resources,
            "successful_resources": workflow_state.deployment_result.successful_resources,
            "deployment_id": workflow_state.deployment_result.deployment_id,
        }

    return response


@app.get("/api/workflow/{workflow_id}/bicep")
async def download_bicep_code(workflow_id: str):
    """
    Download the generated Bicep code for a workflow.

    Args:
        workflow_id: Workflow identifier

    Returns:
        Bicep file content
    """
    if workflow_id not in workflow_states:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow_state = workflow_states[workflow_id]

    if not workflow_state.bicep_code:
        raise HTTPException(
            status_code=400, detail="Bicep code not yet generated for this workflow"
        )

    # Save Bicep code to temp file
    bicep_file = UPLOAD_DIR / f"{workflow_id}.bicep"
    async with aiofiles.open(bicep_file, "w") as f:
        await f.write(workflow_state.bicep_code.bicep_code)

    return FileResponse(
        path=bicep_file,
        media_type="text/plain",
        filename=f"infrastructure-{workflow_id}.bicep",
    )


@app.get("/api/workflow/{workflow_id}/corrected-bicep")
async def download_corrected_bicep_code(workflow_id: str):
    """
    Download the corrected Bicep code for a workflow.

    Args:
        workflow_id: Workflow identifier

    Returns:
        Corrected Bicep file content with auto-fixes applied
    """
    if workflow_id not in workflow_states:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow_state = workflow_states[workflow_id]

    if not workflow_state.corrected_bicep_code:
        raise HTTPException(
            status_code=400, detail="Corrected Bicep code not yet generated for this workflow"
        )

    # Save corrected Bicep code to temp file
    bicep_file = UPLOAD_DIR / f"{workflow_id}-corrected.bicep"
    async with aiofiles.open(bicep_file, "w") as f:
        await f.write(workflow_state.corrected_bicep_code.bicep_code)

    return FileResponse(
        path=bicep_file,
        media_type="text/plain",
        filename=f"infrastructure-{workflow_id}-corrected.bicep",
    )


@app.get("/api/workflow/{workflow_id}/results")
async def get_workflow_results(workflow_id: str):
    """
    Get complete results of a completed workflow.

    Args:
        workflow_id: Workflow identifier

    Returns:
        Complete workflow results including all stages
    """
    if workflow_id not in workflow_states:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow_state = workflow_states[workflow_id]

    if not workflow_state.is_completed:
        raise HTTPException(
            status_code=400, detail="Workflow not yet completed"
        )

    # Return complete workflow state
    return {
        "workflow_id": workflow_state.workflow_id,
        "source_image": workflow_state.source_image,
        "started_at": workflow_state.started_at.isoformat(),
        "completed_at": workflow_state.completed_at.isoformat()
        if workflow_state.completed_at
        else None,
        "final_stage": workflow_state.current_stage.value,
        "has_errors": workflow_state.has_errors,
        "error_message": workflow_state.error_message,
        "diagram_analysis": workflow_state.diagram_analysis.dict()
        if workflow_state.diagram_analysis
        else None,
        "resource_specification": workflow_state.resource_specification.dict()
        if workflow_state.resource_specification
        else None,
        "validation_result": workflow_state.validation_result.dict()
        if workflow_state.validation_result
        else None,
        "deployment_result": workflow_state.deployment_result.dict()
        if workflow_state.deployment_result
        else None,
    }


async def process_diagram_workflow(
    workflow_id: str,
    image_path: Path,
    resource_group: Optional[str],
    location: Optional[str],
):
    """
    Background task to process the diagram through the complete workflow.

    Args:
        workflow_id: Workflow identifier
        image_path: Path to uploaded diagram
        resource_group: Target resource group
        location: Target Azure region
    """
    logger.info(f"Starting background workflow processing: {workflow_id}")

    try:
        # Run the workflow
        result = await run_workflow(
            image_path=image_path,
            resource_group=resource_group or settings.azure_deployment.resource_group,
            location=location or settings.azure_deployment.location,
        )

        # Update stored workflow state
        workflow_states[workflow_id] = result

        logger.info(f"Workflow {workflow_id} completed successfully")

    except Exception as e:
        logger.error(f"Workflow {workflow_id} failed: {e}", exc_info=True)
        
        # Update workflow state with error
        if workflow_id in workflow_states:
            workflow_states[workflow_id].has_errors = True
            workflow_states[workflow_id].error_message = str(e)
            workflow_states[workflow_id].current_stage = WorkflowStage.FAILED
            workflow_states[workflow_id].completed_at = datetime.utcnow()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=settings.api.host,
        port=settings.api.port,
        log_level=settings.monitoring.log_level.lower(),
    )
