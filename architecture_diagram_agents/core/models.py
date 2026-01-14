"""
Data models and schemas for the Architecture Diagram Analyzer.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum


class CloudProvider(Enum):
    """Supported cloud providers."""
    AZURE = "Microsoft Azure"
    AWS = "Amazon Web Services"
    GCP = "Google Cloud Platform"
    OTHER = "Other"


class ServiceCategory(Enum):
    """Azure service categories."""
    COMPUTE = "Compute"
    STORAGE = "Storage"
    DATABASE = "Database"
    NETWORKING = "Networking"
    AI_ML = "AI + ML"
    INTEGRATION = "Integration"
    SECURITY = "Security"
    MONITORING = "Monitoring"


@dataclass
class BoundingBox:
    """Bounding box coordinates."""
    x: int
    y: int
    width: int
    height: int
    
    def to_dict(self) -> Dict[str, int]:
        return asdict(self)


@dataclass
class ImageCaption:
    """Image caption with confidence and optional bounding box."""
    text: str
    confidence: float
    bounding_box: Optional[BoundingBox] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "bounding_box": self.bounding_box.to_dict() if self.bounding_box else None
        }


@dataclass
class ImageTag:
    """Image tag with confidence score."""
    name: str
    confidence: float
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DetectedObject:
    """Detected object with bounding box."""
    name: str
    confidence: float
    bounding_box: BoundingBox
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "confidence": self.confidence,
            "bounding_box": self.bounding_box.to_dict()
        }


@dataclass
class ExtractedText:
    """OCR extracted text with location."""
    text: str
    bounding_polygon: Optional[List[Dict[str, int]]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VisionAnalysisResult:
    """Complete vision analysis result."""
    dense_captions: List[ImageCaption] = field(default_factory=list)
    tags: List[ImageTag] = field(default_factory=list)
    objects: List[DetectedObject] = field(default_factory=list)
    text: List[ExtractedText] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "dense_captions": [c.to_dict() for c in self.dense_captions],
            "tags": [t.to_dict() for t in self.tags],
            "objects": [o.to_dict() for o in self.objects],
            "text": [t.to_dict() for t in self.text],
            "metadata": self.metadata
        }


@dataclass
class AzureService:
    """Azure service recommendation."""
    service_name: str
    category: ServiceCategory
    description: str
    region: str = "uaenorth"
    
    def to_dict(self) -> Dict[str, str]:
        return {
            "service_name": self.service_name,
            "category": self.category.value,
            "description": self.description,
            "region": self.region
        }


@dataclass
class AgentAnalysisResult:
    """Agent analysis result for architecture recommendations."""
    cloud_provider: CloudProvider
    azure_services: List[AzureService] = field(default_factory=list)
    summary: str = ""
    is_architecture_diagram: bool = True
    default_region: str = "uaenorth"
    analysis_method: str = "AI Agent"
    
    @property
    def total_services(self) -> int:
        return len(self.azure_services)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "cloud_provider": self.cloud_provider.value,
            "azure_services": [s.to_dict() for s in self.azure_services],
            "summary": self.summary,
            "is_architecture_diagram": self.is_architecture_diagram,
            "default_region": self.default_region,
            "total_services": self.total_services,
            "analysis_method": self.analysis_method
        }


@dataclass
class AnalysisResult:
    """Complete analysis result combining vision and agent analysis."""
    vision_analysis: VisionAnalysisResult
    agent_analysis: AgentAnalysisResult
    timestamp: datetime = field(default_factory=datetime.utcnow)
    success: bool = True
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "timestamp": self.timestamp.isoformat(),
            "computer_vision": {
                "data": self.vision_analysis.to_dict(),
                "summary": self._get_vision_summary()
            },
            "agent_analysis": self.agent_analysis.to_dict(),
            "error_message": self.error_message
        }
    
    def _get_vision_summary(self) -> Dict[str, Any]:
        """Generate vision analysis summary."""
        return {
            "total_captions": len(self.vision_analysis.dense_captions),
            "total_tags": len(self.vision_analysis.tags),
            "total_objects": len(self.vision_analysis.objects),
            "total_text_lines": len(self.vision_analysis.text)
        }


@dataclass
class ImageData:
    """Container for image data."""
    data: bytes
    filename: str
    content_type: str
    size_bytes: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "filename": self.filename,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes
        }
