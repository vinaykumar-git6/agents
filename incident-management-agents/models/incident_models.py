"""
Data models for the Incident Management System.
"""
from datetime import datetime
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field


class IncidentPriority(str, Enum):
    """ServiceNow incident priority levels."""
    CRITICAL = "1"
    HIGH = "2"
    MODERATE = "3"
    LOW = "4"


class IncidentStatus(str, Enum):
    """Incident workflow status."""
    NEW = "new"
    ANALYZING = "analyzing"
    PLANNING = "planning"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    REMEDIATING = "remediating"
    RESOLVED = "resolved"
    FAILED = "failed"


class ApprovalStatus(str, Enum):
    """Approval status for remediation actions."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ServiceNowIncident(BaseModel):
    """ServiceNow incident data received via webhook."""
    sys_id: str = Field(..., description="ServiceNow incident system ID")
    number: str = Field(..., description="Incident number (e.g., INC0012345)")
    short_description: str = Field(..., description="Brief description of the incident")
    description: Optional[str] = Field(None, description="Detailed incident description")
    priority: IncidentPriority = Field(..., description="Incident priority")
    urgency: str = Field(..., description="Incident urgency")
    impact: str = Field(..., description="Business impact")
    category: Optional[str] = Field(None, description="Incident category")
    subcategory: Optional[str] = Field(None, description="Incident subcategory")
    assigned_to: Optional[str] = Field(None, description="Assigned user")
    configuration_item: Optional[str] = Field(None, description="Affected CI")
    state: str = Field(..., description="Current incident state")
    opened_at: datetime = Field(..., description="Incident creation timestamp")
    additional_comments: Optional[str] = Field(None, description="Additional comments")
    
    class Config:
        json_schema_extra = {
            "example": {
                "sys_id": "abc123def456",
                "number": "INC0012345",
                "short_description": "Application server not responding",
                "description": "Users are unable to access the customer portal. Application server appears to be down.",
                "priority": "2",
                "urgency": "2",
                "impact": "2",
                "category": "Infrastructure",
                "subcategory": "Server",
                "configuration_item": "PROD-APP-SERVER-01",
                "state": "2",
                "opened_at": "2025-11-14T10:30:00Z"
            }
        }


class IncidentSummary(BaseModel):
    """Analyzed and summarized incident information."""
    incident_id: str = Field(..., description="Original ServiceNow incident ID")
    incident_number: str = Field(..., description="Incident number")
    summary: str = Field(..., description="Concise summary of the issue")
    severity: str = Field(..., description="Analyzed severity level")
    affected_service: str = Field(..., description="Affected service or component")
    symptoms: list[str] = Field(..., description="List of observed symptoms")
    potential_root_causes: list[str] = Field(..., description="Potential root causes identified")
    business_impact: str = Field(..., description="Business impact assessment")
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)


class RemediationAction(BaseModel):
    """Individual remediation action to be performed."""
    action_id: str = Field(..., description="Unique action identifier")
    action_type: str = Field(..., description="Type of action (restart, scale, config, etc.)")
    target_resource: str = Field(..., description="Target Azure resource")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Action parameters")
    description: str = Field(..., description="Human-readable action description")
    estimated_duration_minutes: int = Field(..., description="Estimated execution time")
    risk_level: str = Field(..., description="Risk level (low, medium, high)")


class RemediationPlan(BaseModel):
    """Complete remediation plan for an incident."""
    incident_id: str = Field(..., description="Associated incident ID")
    plan_id: str = Field(..., description="Unique plan identifier")
    summary: str = Field(..., description="Plan summary")
    actions: list[RemediationAction] = Field(..., description="Ordered list of remediation actions")
    estimated_total_duration_minutes: int = Field(..., description="Total estimated duration")
    knowledge_base_references: list[str] = Field(
        default_factory=list, description="KB articles referenced"
    )
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Plan confidence score")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ApprovalRequest(BaseModel):
    """Human approval request for remediation plan."""
    approval_id: str = Field(..., description="Unique approval request ID")
    incident_id: str = Field(..., description="Associated incident ID")
    plan_id: str = Field(..., description="Associated plan ID")
    remediation_plan: RemediationPlan = Field(..., description="Plan to be approved")
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime = Field(..., description="Approval expiration time")
    status: ApprovalStatus = Field(default=ApprovalStatus.PENDING)
    approved_by: Optional[str] = Field(None, description="Approver email")
    approved_at: Optional[datetime] = Field(None)
    rejection_reason: Optional[str] = Field(None)


class RemediationResult(BaseModel):
    """Result of a single remediation action."""
    action_id: str = Field(..., description="Action identifier")
    status: str = Field(..., description="Execution status (success, failed, skipped)")
    start_time: datetime = Field(..., description="Action start time")
    end_time: datetime = Field(..., description="Action end time")
    output: Optional[str] = Field(None, description="Action output")
    error_message: Optional[str] = Field(None, description="Error message if failed")


class RemediationExecution(BaseModel):
    """Complete remediation execution record."""
    execution_id: str = Field(..., description="Unique execution ID")
    incident_id: str = Field(..., description="Associated incident ID")
    plan_id: str = Field(..., description="Associated plan ID")
    approval_id: str = Field(..., description="Associated approval ID")
    results: list[RemediationResult] = Field(default_factory=list)
    overall_status: str = Field(..., description="Overall execution status")
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = Field(None)


class IncidentResolution(BaseModel):
    """Final incident resolution with RCA."""
    incident_id: str = Field(..., description="ServiceNow incident ID")
    root_cause: str = Field(..., description="Root cause analysis")
    remediation_summary: str = Field(..., description="Summary of actions taken")
    actions_performed: list[RemediationResult] = Field(..., description="Detailed action results")
    resolution_notes: str = Field(..., description="Resolution notes")
    resolved_at: datetime = Field(default_factory=datetime.utcnow)


class WorkflowState(BaseModel):
    """Workflow state tracking in Cosmos DB."""
    workflow_id: str = Field(..., description="Unique workflow execution ID")
    incident_id: str = Field(..., description="ServiceNow incident ID")
    current_status: IncidentStatus = Field(..., description="Current workflow status")
    incident_data: Optional[ServiceNowIncident] = Field(None)
    incident_summary: Optional[IncidentSummary] = Field(None)
    remediation_plan: Optional[RemediationPlan] = Field(None)
    approval_request: Optional[ApprovalRequest] = Field(None)
    remediation_execution: Optional[RemediationExecution] = Field(None)
    resolution: Optional[IncidentResolution] = Field(None)
    error_message: Optional[str] = Field(None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_schema_extra = {
            "example": {
                "workflow_id": "wf_abc123",
                "incident_id": "INC0012345",
                "current_status": "analyzing",
                "created_at": "2025-11-14T10:30:00Z",
                "updated_at": "2025-11-14T10:32:00Z"
            }
        }
