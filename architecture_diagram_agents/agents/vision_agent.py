"""
Vision Analysis Agent - Architecture Diagram Analysis using Azure Computer Vision.
Handles image analysis using Azure Computer Vision OCR and Agent Framework.
"""

import asyncio
import os
import json
import base64
from typing import Optional
from pathlib import Path

from azure.identity import AzureCliCredential
from azure.ai.vision.imageanalysis import ImageAnalysisClient
from azure.ai.vision.imageanalysis.models import VisualFeatures
from dotenv import load_dotenv

from ..core.config import Config
from ..utils.legacy_utils import setup_logger
from ..utils.logging_config import setup_logging
from ..utils.telemetry import trace_operation, add_event, set_attribute

# Load .env from project root
env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=env_path, override=True)

# Initialize logging
setup_logging(level="INFO")

logger = setup_logger(__name__)

# Configuration
vision_endpoint = os.environ.get("AZURE_COMPUTER_VISION_ENDPOINT")


class VisionAgent:
    """
    Agent for analyzing architecture diagrams using Azure Computer Vision.
    
    Capabilities:
    - Dense caption generation (via Computer Vision API)
    - Tag extraction (via Computer Vision API)
    - Object detection (via Computer Vision API)
    - Text recognition / OCR (via Computer Vision API)
    - Service identification (tag-based Azure service detection)
    """
    
    def __init__(self, config: Optional[Config] = None):
        """
        Initialize Vision Agent.
        
        Args:
            config: Application configuration (optional)
        """
        self.config = config or Config.from_environment()
        self.vision_endpoint = vision_endpoint or self.config.computer_vision_endpoint
        self.vision_client: Optional[ImageAnalysisClient] = None
        self._initialized = False
        logger.info("VisionAgent instantiated")
    
    async def initialize(self) -> None:
        """Initialize Azure Computer Vision for vision analysis."""
        if self._initialized:
            return
        
        try:
            credential = AzureCliCredential()
            
            # Initialize Computer Vision client
            self.vision_client = ImageAnalysisClient(
                endpoint=self.vision_endpoint,
                credential=credential
            )
            
            self._initialized = True
            logger.info("VisionAgent initialized successfully with Computer Vision")
            
        except Exception as e:
            logger.error(f"Failed to initialize VisionAgent: {e}")
            raise
    
    async def analyze(self, image_path: str) -> dict:
        """
        Analyze an architecture diagram image using Computer Vision and Agent Framework.
        
        Args:
            image_path: Path to the image file
        
        Returns:
            Dictionary with vision analysis results
        """
        if not self._initialized:
            await self.initialize()
        
        with trace_operation("vision_agent_analyze", {"image_path": image_path}):
            try:
                # Verify image exists
                if not Path(image_path).exists():
                    raise FileNotFoundError(f"Image not found: {image_path}")
                
                logger.info(f"Analyzing image: {image_path}")
                add_event("vision_analysis_started", {"image_path": image_path})
                
                # ==========================================
                # Step 1: Analyze with Azure Computer Vision
                # ==========================================
                logger.info("Running Computer Vision analysis...")
                
                # Read image file
                with open(image_path, "rb") as img_file:
                    image_data = img_file.read()
                
                set_attribute("image_size_bytes", len(image_data))
                
                # Analyze image
                result = self.vision_client.analyze(
                    image_data=image_data,
                    visual_features=[
                        VisualFeatures.DENSE_CAPTIONS,
                        VisualFeatures.TAGS,
                        VisualFeatures.OBJECTS,
                        VisualFeatures.READ
                    ]
                )
            
                # Extract Computer Vision results
                dense_captions = []
                if result.dense_captions:
                    for caption in result.dense_captions:
                        # Handle both object with .text and string directly
                        text = caption.text if hasattr(caption, 'text') else str(caption)
                        dense_captions.append(text)
                
                tags = []
                if result.tags:
                    for tag in result.tags:
                        # Handle both object with .name and string directly
                        name = tag.name if hasattr(tag, 'name') else str(tag)
                        tags.append(name)
                
                objects = []
                if result.objects:
                    for obj in result.objects:
                        try:
                            obj_name = obj.tags[0].name if obj.tags else "Unknown"
                            confidence = obj.tags[0].confidence if obj.tags else 0
                        except (AttributeError, IndexError, TypeError):
                            obj_name = "Unknown"
                            confidence = 0
                        
                        try:
                            objects.append({
                                "name": obj_name,
                                "confidence": confidence,
                                "bounds": {
                                    "x": obj.bounding_box.x,
                                    "y": obj.bounding_box.y,
                                    "w": obj.bounding_box.w,
                                    "h": obj.bounding_box.h
                                }
                            })
                        except (AttributeError, TypeError):
                            objects.append({
                                "name": obj_name,
                                "confidence": confidence,
                                "bounds": {}
                            })
                
                text_results = []
                if result.read:
                    for block in result.read.blocks:
                        for line in block.lines:
                            text = line.text if hasattr(line, 'text') else str(line)
                            text_results.append(text)
                
                logger.info(f"Computer Vision results: {len(dense_captions)} captions, {len(tags)} tags, {len(objects)} objects, {len(text_results)} text items")
                
                # ==========================================
                # Step 2: Identify Azure services from tags and text
                # ==========================================
                logger.info("Identifying Azure services from analysis results...")
                
                # Extract Azure services from tags and text
                services_detected = self._extract_azure_services(tags, text_results)
                architecture_type = self._infer_architecture_type(tags, text_results)
                complexity = self._calculate_complexity(len(objects), len(tags))
                
                # ==========================================
                # Step 3: Combine results
                # ==========================================
                analysis_result = {
                    "dense_captions": dense_captions,
                    "tags": tags,
                    "objects": objects,
                    "text": text_results,
                    "architecture_type": architecture_type,
                    "services_detected": services_detected,
                    "service_descriptions": {},
                    "complexity": complexity,
                    "data_flows": []
                }
                
                logger.info(f"Service identification completed: {len(services_detected)} services identified")
                logger.info("Vision analysis completed successfully")
                logger.info(f"Computer Vision results: {analysis_result}")
                return analysis_result
            
            except Exception as e:
                logger.error(f"Vision analysis failed: {e}")
                raise
    
    def _extract_azure_services(self, tags: list, text_results: list) -> list:
        """Extract Azure services from tags and OCR text."""
        azure_keywords = {
            # Compute
            'app service', 'web app', 'function', 'azure functions', 'logic apps',
            'container', 'aks', 'kubernetes', 'container instances', 'aci',
            'virtual machine', 'vm', 'vmss', 'virtual machine scale sets',
            'batch', 'azure batch', 'spring cloud', 'azure spring apps',
            
            # Containers & Registry
            'container registry', 'acr', 'azure container registry',
            'container apps', 'azure container apps',
            
            # Storage
            'storage', 'azure storage', 'blob storage', 'blob', 'file storage',
            'queue storage', 'table storage', 'data lake', 'azure data lake',
            'disk', 'managed disk', 'storage account',
            
            # Database
            'sql database', 'azure sql', 'sql server', 'sql managed instance',
            'cosmos db', 'cosmosdb', 'mysql', 'postgresql', 'mariadb',
            'redis', 'azure cache', 'cache for redis',
            
            # Networking
            'load balancer', 'application gateway', 'app gateway', 'agw',
            'traffic manager', 'front door', 'azure front door',
            'vpn gateway', 'virtual network', 'vnet', 'subnet',
            'firewall', 'azure firewall', 'nat gateway', 'bastion',
            'private link', 'private endpoint', 'dns', 'azure dns',
            'cdn', 'azure cdn', 'express route', 'expressroute',
            
            # Monitoring & Management
            'monitor', 'azure monitor', 'application insights', 'app insights',
            'log analytics', 'log analytics workspace', 'logs',
            'alerts', 'metrics', 'workbooks', 'dashboard', 'grafana',
            'managed grafana', 'azure managed grafana',
            
            # Integration
            'service bus', 'event hub', 'event hubs', 'event grid',
            'api management', 'apim', 'relay', 'azure relay',
            
            # Data & Analytics
            'data factory', 'synapse', 'synapse analytics', 'azure synapse',
            'databricks', 'azure databricks', 'hdinsight', 'stream analytics',
            'purview', 'data catalog', 'analysis services',
            
            # AI & ML
            'machine learning', 'azure ml', 'cognitive services', 'openai',
            'azure openai', 'computer vision', 'form recognizer', 'bot service',
            'ai search', 'cognitive search', 'azure search',
            
            # Security & Identity
            'key vault', 'azure ad', 'entra id', 'active directory',
            'security center', 'defender', 'microsoft defender',
            'sentinel', 'azure sentinel', 'information protection',
            'managed identity', 'rbac', 'conditional access',
            
            # DevOps & Development
            'devops', 'azure devops', 'repos', 'pipelines', 'artifacts',
            'github', 'github actions', 'deployment slots',
            
            # IoT
            'iot hub', 'iot central', 'digital twins', 'azure digital twins',
            'sphere', 'azure sphere', 'time series insights'
        }
        
        services = set()
        all_text = ' '.join(tags + text_results).lower()
        
        for keyword in azure_keywords:
            if keyword in all_text:
                services.add(keyword)
        
        return sorted(list(services))
    
    def _infer_architecture_type(self, tags: list, text_results: list) -> str:
        """Infer architecture type from tags and text."""
        all_text = ' '.join(tags + text_results).lower()
        
        if 'function' in all_text or 'serverless' in all_text:
            return 'serverless'
        elif 'microservice' in all_text or 'container' in all_text or 'kubernetes' in all_text:
            return 'microservices'
        elif 'monolith' in all_text or 'monolithic' in all_text:
            return 'monolith'
        elif 'hybrid' in all_text:
            return 'hybrid'
        else:
            return 'unknown'
    
    def _calculate_complexity(self, object_count: int, tag_count: int) -> str:
        """Calculate architecture complexity."""
        total_components = object_count + tag_count
        
        if total_components < 5:
            return 'simple'
        elif total_components < 15:
            return 'moderate'
        else:
            return 'complex'
    
    async def close(self) -> None:
        """Close the agent connection and release resources."""
        try:
            if self.vision_client:
                # ImageAnalysisClient may have a close method
                if hasattr(self.vision_client, 'close'):
                    if asyncio.iscoroutinefunction(self.vision_client.close):
                        await self.vision_client.close()
                    else:
                        self.vision_client.close()
            self._initialized = False
            self.vision_client = None
            logger.info("VisionAgent closed successfully")
        except Exception as e:
            logger.warning(f"Error closing VisionAgent: {e}")


async def main():
    """Test the Vision Agent."""
    try:
        agent = VisionAgent()
        await agent.initialize()
        logger.info("VisionAgent ready for use")
        
    except Exception as e:
        logger.error(f"Failed to initialize VisionAgent: {e}")
        return None


if __name__ == "__main__":
    asyncio.run(main())
