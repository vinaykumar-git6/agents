"""
Data models for Architecture Diagram to IaC multi-agent workflow.

Models represent data flowing between agents:
1. DiagramAnalysis: Raw extraction from Computer Vision
2. ResourceSpecification: Synthesized resource information
3. BicepCode: Generated infrastructure as code
4. ValidationResult: Review feedback and issues
5. DeploymentResult: Deployment execution results
"""

from datetime import datetime
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field, field_validator


# ================================
# Enums
# ================================


class ResourceType(str, Enum):
    """Azure resource types that can be extracted from diagrams."""

    # Compute
    VIRTUAL_MACHINE = "Microsoft.Compute/virtualMachines"
    APP_SERVICE = "Microsoft.Web/sites"
    FUNCTION_APP = "Microsoft.Web/sites"  # functio apps use same type with kind
    CONTAINER_APP = "Microsoft.App/containerApps"
    AKS_CLUSTER = "Microsoft.ContainerService/managedClusters"
    
    # Storage
    STORAGE_ACCOUNT = "Microsoft.Storage/storageAccounts"
    COSMOS_DB = "Microsoft.DocumentDB/databaseAccounts"
    SQL_DATABASE = "Microsoft.Sql/servers"
    
    # Networking
    VIRTUAL_NETWORK = "Microsoft.Network/virtualNetworks"
    LOAD_BALANCER = "Microsoft.Network/loadBalancers"
    APPLICATION_GATEWAY = "Microsoft.Network/applicationGateways"
    PUBLIC_IP = "Microsoft.Network/publicIPAddresses"
    NETWORK_SECURITY_GROUP = "Microsoft.Network/networkSecurityGroups"
    
    # AI & Analytics
    AI_SERVICE = "Microsoft.CognitiveServices/accounts"
    AI_SEARCH = "Microsoft.Search/searchServices"
    MACHINE_LEARNING = "Microsoft.MachineLearningServices/workspaces"
    
    # Messaging
    SERVICE_BUS = "Microsoft.ServiceBus/namespaces"
    EVENT_HUB = "Microsoft.EventHub/namespaces"
    EVENT_GRID = "Microsoft.EventGrid/topics"
    
    # Security & Identity
    KEY_VAULT = "Microsoft.KeyVault/vaults"
    
    # Monitoring
    LOG_ANALYTICS = "Microsoft.OperationalInsights/workspaces"
    APPLICATION_INSIGHTS = "Microsoft.Insights/components"
    
    # Other
    RESOURCE_GROUP = "Microsoft.Resources/resourceGroups"
    UNKNOWN = "Unknown"


class SeverityLevel(str, Enum):
    """Issue severity levels for validation."""

    CRITICAL = "critical"  # Blocks deployment
    ERROR = "error"  # Should be fixed
    WARNING = "warning"  # Should be reviewed
    INFO = "info"  # Informational


class DeploymentStatus(str, Enum):
    """Deployment execution status."""

    PENDING = "pending"
    VALIDATING = "validating"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ================================
# Stage 1: Computer Vision Output
# ================================


class ExtractedResource(BaseModel):
    """A single Azure resource extracted from the architecture diagram."""

    # Basic identification
    detected_name: str = Field(..., description="Name detected in the diagram")
    resource_type: ResourceType = Field(..., description="Detected Azure resource type")
    confidence_score: float = Field(
        ..., ge=0.0, le=1.0, description="Detection confidence (0.0-1.0)"
    )
    
    # Location information
    bounding_box: Optional[dict[str, float]] = Field(
        default=None,
        description="Position in diagram {x, y, width, height}",
    )
    
    # Extracted properties
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted properties (location, SKU, etc.)",
    )
    
    # Relationships
    connected_to: list[str] = Field(
        default_factory=list,
        description="Names of connected resources",
    )
    
    # Metadata
    annotations: list[str] = Field(
        default_factory=list,
        description="Text annotations near the resource",
    )


class DiagramAnalysis(BaseModel):
    """Complete analysis output from Computer Vision service."""

    # Image information
    image_filename: str = Field(..., description="Source image filename")
    image_size: dict[str, int] = Field(..., description="Image dimensions {width, height}")
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Extracted resources
    resources: list[ExtractedResource] = Field(
        default_factory=list,
        description="All detected Azure resources",
    )
    
    # Extracted text and annotations
    detected_text: list[str] = Field(
        default_factory=list,
        description="All text detected in diagram",
    )
    
    # Overall analysis
    overall_confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Overall analysis confidence"
    )
    
    # Metadata
    analysis_notes: list[str] = Field(
        default_factory=list,
        description="Notes about the analysis process",
    )

    @field_validator("resources")
    @classmethod
    def validate_resources(cls, v: list[ExtractedResource]) -> list[ExtractedResource]:
        """Ensure at least one resource was detected."""
        if not v:
            raise ValueError("No resources detected in diagram")
        return v


# ================================
# Stage 2: Resource Analysis Output
# ================================


class ResourceDependency(BaseModel):
    """Dependency relationship between resources."""

    source: str = Field(..., description="Source resource name")
    target: str = Field(..., description="Target resource name")
    dependency_type: str = Field(..., description="Type of dependency (e.g., 'network', 'reference')")


class SynthesizedResource(BaseModel):
    """A fully analyzed and normalized resource specification."""

    # Naming
    resource_name: str = Field(..., description="Normalized Azure resource name")
    resource_type: ResourceType = Field(..., description="Azure resource type")
    
    # Deployment info
    location: str = Field(..., description="Azure region (e.g., 'eastus')")
    resource_group: str = Field(..., description="Target resource group name")
    
    # Configuration
    sku: Optional[str] = Field(default=None, description="SKU/tier (e.g., 'Standard_LRS')")
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Resource-specific properties",
    )
    tags: dict[str, str] = Field(
        default_factory=dict,
        description="Resource tags",
    )
    
    # Dependencies
    depends_on: list[str] = Field(
        default_factory=list,
        description="Resource names this depends on",
    )
    
    # Metadata
    deployment_order: int = Field(..., description="Order in deployment sequence")
    notes: list[str] = Field(
        default_factory=list,
        description="Analysis notes or warnings",
    )


class ResourceSpecification(BaseModel):
    """Complete specification for all resources to be created."""

    # Metadata
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    source_diagram: str = Field(..., description="Source diagram filename")
    
    # Global settings
    default_location: str = Field(default="eastus", description="Default Azure region")
    default_resource_group: str = Field(..., description="Default resource group")
    
    # Resources
    resources: list[SynthesizedResource] = Field(..., description="All resources to create")
    
    # Dependencies
    dependencies: list[ResourceDependency] = Field(
        default_factory=list,
        description="Resource dependencies",
    )
    
    # Parameters
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Bicep parameters to be templated",
    )
    
    # Analysis summary
    total_resources: int = Field(..., description="Total resource count")
    resource_types_summary: dict[str, int] = Field(
        default_factory=dict,
        description="Count by resource type",
    )
    
    # Validation
    validation_notes: list[str] = Field(
        default_factory=list,
        description="Notes from resource analysis",
    )


# ================================
# Stage 3: IaC Generation Output
# ================================


class BicepParameter(BaseModel):
    """Bicep parameter definition."""

    name: str
    type: str  # string, int, bool, object, array
    default_value: Optional[Any] = None
    description: Optional[str] = None
    allowed_values: Optional[list[Any]] = None


class BicepVariable(BaseModel):
    """Bicep variable definition."""

    name: str
    value: Any
    description: Optional[str] = None


class BicepResource(BaseModel):
    """Bicep resource definition."""

    symbolic_name: str = Field(..., description="Bicep symbolic name")
    resource_type: str = Field(..., description="Azure resource type")
    api_version: str = Field(..., description="API version")
    name_expression: str = Field(..., description="Name expression in Bicep")
    properties: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


class BicepOutput(BaseModel):
    """Bicep output definition."""

    name: str
    type: str
    value_expression: str
    description: Optional[str] = None


class BicepCode(BaseModel):
    """Generated Bicep infrastructure as code."""

    # Metadata
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    source_specification: str = Field(..., description="Source specification reference")
    
    # Bicep components
    parameters: list[BicepParameter] = Field(default_factory=list)
    variables: list[BicepVariable] = Field(default_factory=list)
    resources: list[BicepResource] = Field(..., description="Resource definitions")
    outputs: list[BicepOutput] = Field(default_factory=list)
    
    # Complete code
    bicep_code: str = Field(..., description="Complete Bicep file content")
    
    # Metadata
    target_scope: str = Field(default="resourceGroup", description="Deployment scope")
    version: str = Field(default="1.0", description="Template version")
    
    # Generation notes
    generation_notes: list[str] = Field(
        default_factory=list,
        description="Notes from IaC generation",
    )


# ================================
# Stage 4: IaC Review Output
# ================================


class ValidationIssue(BaseModel):
    """A single validation issue found during review."""

    severity: SeverityLevel
    category: str = Field(..., description="Issue category (e.g., 'security', 'syntax', 'best-practice')")
    message: str = Field(..., description="Issue description")
    location: Optional[str] = Field(
        default=None,
        description="Location in code (e.g., 'line 42', 'resource storageAccount')",
    )
    suggestion: Optional[str] = Field(
        default=None,
        description="Suggested fix",
    )
    rule_id: Optional[str] = Field(
        default=None,
        description="Rule ID if from linter",
    )


class ValidationResult(BaseModel):
    """Complete validation result from IaC review."""

    # Metadata
    reviewed_at: datetime = Field(default_factory=datetime.utcnow)
    bicep_source: str = Field(..., description="Source Bicep code reference")
    
    # Overall status
    is_valid: bool = Field(..., description="Whether code passes validation")
    has_critical_issues: bool = Field(default=False)
    has_errors: bool = Field(default=False)
    
    # Issues
    issues: list[ValidationIssue] = Field(default_factory=list)
    
    # Issue summary
    issue_summary: dict[str, int] = Field(
        default_factory=dict,
        description="Count by severity level",
    )
    
    # Validation details
    syntax_valid: bool = Field(..., description="Bicep syntax validation passed")
    linter_passed: bool = Field(default=True, description="Linter validation passed")
    security_check_passed: bool = Field(default=True, description="Security checks passed")
    best_practices_passed: bool = Field(default=True, description="Best practices validation passed")
    
    # Recommendations
    recommendations: list[str] = Field(
        default_factory=list,
        description="General recommendations",
    )
    
    # Corrected code (if issues were auto-fixed)
    corrected_bicep_code: Optional[str] = Field(
        default=None,
        description="Auto-corrected Bicep code",
    )
    
    # Review notes
    review_notes: list[str] = Field(
        default_factory=list,
        description="Notes from review process",
    )


# ================================
# Stage 5: Deployment Output
# ================================


class DeployedResource(BaseModel):
    """Information about a deployed resource."""

    resource_name: str
    resource_type: str
    resource_id: str = Field(..., description="Full Azure resource ID")
    status: str = Field(..., description="Deployment status")
    provisioning_state: str = Field(..., description="Azure provisioning state")


class DeploymentResult(BaseModel):
    """Result of infrastructure deployment to Azure."""

    # Metadata
    deployment_id: str = Field(..., description="Azure deployment ID")
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    # Status
    status: DeploymentStatus
    
    # Deployment details
    subscription_id: str
    resource_group: str
    location: str
    
    # Resources
    deployed_resources: list[DeployedResource] = Field(default_factory=list)
    failed_resources: list[dict[str, Any]] = Field(default_factory=list)
    
    # Outputs
    deployment_outputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Bicep output values",
    )
    
    # Errors
    error_message: Optional[str] = None
    error_details: Optional[dict[str, Any]] = None
    
    # Summary
    total_resources: int = Field(default=0)
    successful_resources: int = Field(default=0)
    failed_resources_count: int = Field(default=0)
    
    # Logs
    deployment_logs: list[str] = Field(
        default_factory=list,
        description="Deployment execution logs",
    )


# ================================
# Workflow State Tracking
# ================================


class WorkflowStage(str, Enum):
    """Workflow execution stages."""

    VISION_ANALYSIS = "vision_analysis"
    RESOURCE_ANALYSIS = "resource_analysis"
    IAC_GENERATION = "iac_generation"
    IAC_REVIEW = "iac_review"
    IAC_CORRECTION = "iac_correction"
    DEPLOYMENT = "deployment"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowState(BaseModel):
    """Overall workflow state tracking."""

    # Identification
    workflow_id: str = Field(..., description="Unique workflow execution ID")
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    # Current state
    current_stage: WorkflowStage
    
    # Stage data
    diagram_analysis: Optional[DiagramAnalysis] = None
    resource_specification: Optional[ResourceSpecification] = None
    bicep_code: Optional[BicepCode] = None
    validation_result: Optional[ValidationResult] = None
    corrected_bicep_code: Optional[Any] = None  # CorrectedBicepCode type
    deployment_result: Optional[DeploymentResult] = None
    
    # Metadata
    source_image: str = Field(..., description="Source diagram image path")
    created_by: Optional[str] = None
    
    # Status
    is_completed: bool = Field(default=False)
    has_errors: bool = Field(default=False)
    error_message: Optional[str] = None
