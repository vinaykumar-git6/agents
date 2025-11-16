"""Models module initialization."""

from .workflow_models import (
    # Enums
    ResourceType,
    SeverityLevel,
    DeploymentStatus,
    WorkflowStage,
    # Stage 1: Vision Analysis
    ExtractedResource,
    DiagramAnalysis,
    # Stage 2: Resource Analysis
    ResourceDependency,
    SynthesizedResource,
    ResourceSpecification,
    # Stage 3: IaC Generation
    BicepParameter,
    BicepVariable,
    BicepResource,
    BicepOutput,
    BicepCode,
    # Stage 4: IaC Review
    ValidationIssue,
    ValidationResult,
    # Stage 5: Deployment
    DeployedResource,
    DeploymentResult,
    # Workflow State
    WorkflowState,
)

__all__ = [
    # Enums
    "ResourceType",
    "SeverityLevel",
    "DeploymentStatus",
    "WorkflowStage",
    # Stage 1
    "ExtractedResource",
    "DiagramAnalysis",
    # Stage 2
    "ResourceDependency",
    "SynthesizedResource",
    "ResourceSpecification",
    # Stage 3
    "BicepParameter",
    "BicepVariable",
    "BicepResource",
    "BicepOutput",
    "BicepCode",
    # Stage 4
    "ValidationIssue",
    "ValidationResult",
    # Stage 5
    "DeployedResource",
    "DeploymentResult",
    # Workflow
    "WorkflowState",
]
