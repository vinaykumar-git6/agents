"""
Azure Computer Vision service integration for architecture diagram analysis.

Uses Azure Computer Vision API to:
1. Extract text and objects from architecture diagrams
2. Identify Azure service icons and components
3. Detect resource names, configurations, and connections
4. Output structured DiagramAnalysis model

Authentication: Supports both managed identity (preferred) and key-based auth.
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

from azure.ai.vision.imageanalysis import ImageAnalysisClient
from azure.ai.vision.imageanalysis.models import VisualFeatures
from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential
from PIL import Image

from config import settings
from models import DiagramAnalysis, ExtractedResource, ResourceType

logger = logging.getLogger(__name__)


class ComputerVisionService:
    """Service for analyzing architecture diagrams using Azure Computer Vision."""

    # Azure service name patterns for detection
    RESOURCE_PATTERNS = {
        ResourceType.VIRTUAL_MACHINE: [
            r"vm", r"virtual\s*machine", r"compute", r"windows\s*server", r"linux\s*vm"
        ],
        ResourceType.APP_SERVICE: [
            r"app\s*service", r"web\s*app", r"webapp", r"azure\s*app"
        ],
        ResourceType.FUNCTION_APP: [
            r"function", r"func\s*app", r"serverless", r"azure\s*function"
        ],
        ResourceType.STORAGE_ACCOUNT: [
            r"storage", r"blob", r"queue", r"table\s*storage", r"file\s*share"
        ],
        ResourceType.COSMOS_DB: [
            r"cosmos", r"cosmos\s*db", r"cosmosdb", r"document\s*db"
        ],
        ResourceType.SQL_DATABASE: [
            r"sql", r"database", r"azure\s*sql", r"sql\s*server"
        ],
        ResourceType.VIRTUAL_NETWORK: [
            r"vnet", r"virtual\s*network", r"network", r"subnet"
        ],
        ResourceType.AKS_CLUSTER: [
            r"aks", r"kubernetes", r"k8s", r"container\s*cluster"
        ],
        ResourceType.CONTAINER_APP: [
            r"container\s*app", r"aca", r"containerapp"
        ],
        ResourceType.AI_SERVICE: [
            r"cognitive", r"ai\s*service", r"openai", r"vision", r"language"
        ],
        ResourceType.AI_SEARCH: [
            r"search", r"cognitive\s*search", r"ai\s*search"
        ],
        ResourceType.KEY_VAULT: [
            r"key\s*vault", r"keyvault", r"vault", r"secrets"
        ],
        ResourceType.APPLICATION_INSIGHTS: [
            r"app\s*insights", r"application\s*insights", r"appinsights"
        ],
        ResourceType.LOG_ANALYTICS: [
            r"log\s*analytics", r"logs", r"analytics\s*workspace"
        ],
        ResourceType.SERVICE_BUS: [
            r"service\s*bus", r"servicebus", r"message\s*queue"
        ],
        ResourceType.EVENT_HUB: [
            r"event\s*hub", r"eventhub", r"streaming"
        ],
        ResourceType.LOAD_BALANCER: [
            r"load\s*balancer", r"lb", r"loadbalancer"
        ],
        ResourceType.APPLICATION_GATEWAY: [
            r"app\s*gateway", r"application\s*gateway", r"appgw"
        ],
    }

    # Location/region patterns
    LOCATION_PATTERNS = [
        r"(east|west|central|north|south)\s*(us|europe|asia)",
        r"(eastus|westus|centralus|northeurope|westeurope|southeastasia)",
    ]

    def __init__(self):
        """Initialize the Computer Vision service with authentication."""
        self.endpoint = settings.computer_vision.endpoint
        
        # Use managed identity if no key provided (preferred)
        if settings.computer_vision.key:
            credential = AzureKeyCredential(settings.computer_vision.key)
            logger.info("Using key-based authentication for Computer Vision")
        else:
            credential = DefaultAzureCredential()
            logger.info("Using managed identity for Computer Vision")
        
        self.client = ImageAnalysisClient(
            endpoint=self.endpoint,
            credential=credential,
        )

    async def analyze_diagram(
        self,
        image_path: str | Path,
    ) -> DiagramAnalysis:
        """
        Analyze an architecture diagram image and extract Azure resources.

        Args:
            image_path: Path to the architecture diagram image

        Returns:
            DiagramAnalysis: Structured analysis with detected resources

        Raises:
            FileNotFoundError: If image file doesn't exist
            ValueError: If image format is unsupported
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        logger.info(f"Analyzing diagram: {image_path.name}")

        # Get image dimensions
        with Image.open(image_path) as img:
            image_size = {"width": img.width, "height": img.height}
            logger.info(f"Image size: {image_size}")

        # Read image bytes
        with open(image_path, "rb") as f:
            image_data = f.read()

        # Analyze image using Computer Vision
        # Use OCR (Read) + Object Detection + Tags for comprehensive analysis
        result = self.client.analyze(
            image_data=image_data,
            visual_features=[
                VisualFeatures.READ,  # OCR for text extraction
                VisualFeatures.TAGS,  # Image tagging
                VisualFeatures.OBJECTS,  # Object detection
            ],
        )

        # Extract all detected text
        detected_text = []
        if result.read and result.read.blocks:
            for block in result.read.blocks:
                for line in block.lines:
                    detected_text.append(line.text)
                    logger.debug(f"Detected text: {line.text}")

        # Extract resources from text and objects
        resources = self._extract_resources_from_vision_result(
            result, detected_text, image_size
        )

        # Calculate overall confidence
        overall_confidence = self._calculate_overall_confidence(resources)

        # Build analysis notes
        analysis_notes = [
            f"Detected {len(resources)} Azure resources",
            f"Extracted {len(detected_text)} text lines",
        ]

        if overall_confidence < 0.5:
            analysis_notes.append(
                "Low confidence - diagram may be unclear or use non-standard icons"
            )

        return DiagramAnalysis(
            image_filename=image_path.name,
            image_size=image_size,
            resources=resources,
            detected_text=detected_text,
            overall_confidence=overall_confidence,
            analysis_notes=analysis_notes,
        )

    def _extract_resources_from_vision_result(
        self,
        vision_result,
        detected_text: list[str],
        image_size: dict[str, int],
    ) -> list[ExtractedResource]:
        """Extract Azure resources from Computer Vision analysis result."""
        resources = []
        processed_names = set()  # Avoid duplicates

        # Process detected text to find resource names and types
        for idx, text in enumerate(detected_text):
            text_lower = text.lower()

            # Try to match resource type
            resource_type = self._identify_resource_type(text_lower)

            # Skip if it's just a generic word
            if resource_type == ResourceType.UNKNOWN:
                continue

            # Try to extract resource name (usually nearby text or the text itself)
            resource_name = self._extract_resource_name(text, detected_text, idx)

            # Avoid duplicates
            if resource_name in processed_names:
                continue

            processed_names.add(resource_name)

            # Try to extract location
            location = self._extract_location(detected_text, idx)

            # Try to find connected resources
            connected_to = self._find_connections(resource_name, detected_text)

            # Create extracted resource
            resource = ExtractedResource(
                detected_name=resource_name,
                resource_type=resource_type,
                confidence_score=0.8,  # Base confidence for text-based detection
                properties={
                    "location": location if location else "eastus",
                },
                connected_to=connected_to,
                annotations=[text],
            )

            resources.append(resource)
            logger.info(
                f"Detected resource: {resource_name} ({resource_type.value})"
            )

        # If no resources found, add a note
        if not resources:
            logger.warning("No Azure resources detected in diagram")
            # Create a placeholder to avoid validation error
            resources.append(
                ExtractedResource(
                    detected_name="unknown-resource",
                    resource_type=ResourceType.UNKNOWN,
                    confidence_score=0.1,
                    properties={},
                    annotations=["No clear resources detected"],
                )
            )

        return resources

    def _identify_resource_type(self, text: str) -> ResourceType:
        """Identify Azure resource type from text using pattern matching."""
        text = text.lower().strip()

        for resource_type, patterns in self.RESOURCE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    return resource_type

        return ResourceType.UNKNOWN

    def _extract_resource_name(
        self, text: str, all_text: list[str], current_idx: int
    ) -> str:
        """
        Extract resource name from text.
        Look at current text and nearby text for a valid Azure resource name.
        """
        # Clean text for potential resource name
        text_clean = re.sub(r'[^\w\s-]', '', text)

        # If text looks like a resource name (alphanumeric with hyphens)
        if re.match(r'^[a-zA-Z][a-zA-Z0-9-]{2,}$', text_clean):
            return text_clean.lower()

        # Check next text line for name
        if current_idx + 1 < len(all_text):
            next_text = all_text[current_idx + 1]
            next_clean = re.sub(r'[^\w\s-]', '', next_text)
            if re.match(r'^[a-zA-Z][a-zA-Z0-9-]{2,}$', next_clean):
                return next_clean.lower()

        # Check previous text line
        if current_idx > 0:
            prev_text = all_text[current_idx - 1]
            prev_clean = re.sub(r'[^\w\s-]', '', prev_text)
            if re.match(r'^[a-zA-Z][a-zA-Z0-9-]{2,}$', prev_clean):
                return prev_clean.lower()

        # Generate name from resource type
        resource_type = self._identify_resource_type(text)
        if resource_type != ResourceType.UNKNOWN:
            type_name = resource_type.name.lower().replace('_', '-')
            return f"{type_name}-001"

        return f"resource-{current_idx}"

    def _extract_location(self, all_text: list[str], current_idx: int) -> Optional[str]:
        """Extract Azure location/region from nearby text."""
        # Check current and nearby lines for location patterns
        check_range = range(
            max(0, current_idx - 2),
            min(len(all_text), current_idx + 3)
        )

        for idx in check_range:
            text = all_text[idx].lower()
            for pattern in self.LOCATION_PATTERNS:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    location = match.group(0).replace(' ', '').lower()
                    return location

        return None

    def _find_connections(
        self, resource_name: str, all_text: list[str]
    ) -> list[str]:
        """
        Find connections between resources based on proximity and arrow indicators.
        This is a simplified heuristic - real connection detection would use
        image analysis for arrows and lines.
        """
        connections = []

        # Look for arrow indicators near the resource name
        arrow_patterns = [r'->', r'→', r'-->', r'⇒', r'connects to', r'uses']

        for text in all_text:
            text_lower = text.lower()

            # Check if text mentions connection
            for arrow in arrow_patterns:
                if arrow in text_lower and resource_name not in text_lower:
                    # This might reference another resource
                    other_resource_type = self._identify_resource_type(text_lower)
                    if other_resource_type != ResourceType.UNKNOWN:
                        connections.append(text.strip())
                        break

        return connections[:5]  # Limit to 5 connections

    def _calculate_overall_confidence(self, resources: list[ExtractedResource]) -> float:
        """Calculate overall analysis confidence based on detected resources."""
        if not resources:
            return 0.0

        # Average confidence of all resources
        total_confidence = sum(r.confidence_score for r in resources)
        avg_confidence = total_confidence / len(resources)

        # Adjust based on resource count (more resources = higher confidence)
        resource_count_factor = min(1.0, len(resources) / 5.0)

        # Known resources boost confidence
        known_resources = sum(
            1 for r in resources if r.resource_type != ResourceType.UNKNOWN
        )
        known_factor = known_resources / len(resources) if resources else 0.0

        # Final confidence
        final_confidence = (avg_confidence * 0.5 + known_factor * 0.3 + resource_count_factor * 0.2)

        return round(final_confidence, 2)


# Singleton instance
_service_instance: Optional[ComputerVisionService] = None


def get_vision_service() -> ComputerVisionService:
    """Get or create the Computer Vision service singleton."""
    global _service_instance
    if _service_instance is None:
        _service_instance = ComputerVisionService()
    return _service_instance
