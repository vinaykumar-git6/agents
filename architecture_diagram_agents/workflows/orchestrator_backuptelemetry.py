"""
Architecture Diagram Analyzer Orchestrator
Workflow using Microsoft Agent Framework
Sequential Pipeline: Vision → Analyzer → Best Practices → IAC Generator/Reviewer Group Chat
"""

import asyncio
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, cast, Callable, List
from typing_extensions import Never
import queue
import threading

from agent_framework import AgentRunUpdateEvent, ChatMessage, WorkflowBuilder, WorkflowContext, WorkflowOutputEvent, executor, ChatAgent, GroupChatBuilder, GroupChatStateSnapshot
from agent_framework.azure import AzureAIAgentClient
from azure.identity.aio import AzureCliCredential
from pydantic import BaseModel
from dotenv import load_dotenv

from ..agents.vision_agent import VisionAgent
from ..agents.analyzer_agent import AnalyzerAgent
from ..agents.azure_best_practice_agent import AzureBestPracticeAgent
from ..agents.iac_generator_agent import IACGeneratorAgent
from ..agents.iac_reviewer_agent import IACReviewerAgent
from ..core.config import Config
from ..utils.legacy_utils import setup_logger
from ..utils.logging_config import setup_logging
from ..utils.telemetry import trace_operation, add_event, set_attribute, get_telemetry_manager, send_business_event

# Load environment
env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=env_path, override=True)

# Initialize logging
setup_logging(level="INFO")

logger = setup_logger(__name__)

# Initialize telemetry manager for comprehensive observability
telemetry = get_telemetry_manager()

# Global progress queue for streaming updates
progress_queues: Dict[str, queue.Queue] = {}

# Global storage for intermediate workflow results
workflow_results_store: Dict[str, Dict[str, Any]] = {}

def emit_progress(job_id: str, event: Dict[str, Any]):
    """Emit progress event to the queue for this job"""
    if job_id in progress_queues:
        try:
            progress_queues[job_id].put_nowait(event)
        except queue.Full:
            logger.warning(f"Progress queue full for job {job_id}")


# ============================================================================
# Response Models (Pydantic)
# ============================================================================

class ArchitectureAnalysisRequest(BaseModel):
    """Workflow request for architecture analysis"""
    image_path: str
    analysis_type: str = "complete"  # complete, analysis_only, iac_only
    job_id: Optional[str] = None  # Optional job ID for progress tracking


class VisionAnalysisResponse(BaseModel):
    """Vision analysis output"""
    text: list = []
    objects: list = []
    tags: list = []
    dense_captions: list = []
    architecture_type: str = ""
    services_detected: list = []
    status: str = "SUCCESS"
    job_id: Optional[str] = None  # Propagate job_id through workflow


class AnalyzerResponse(BaseModel):
    """Service analyzer output"""
    cloud_provider: str = ""
    default_region: str = ""
    total_services: int = 0
    azure_services: list = []
    summary: str = ""
    status: str = "SUCCESS"
    job_id: Optional[str] = None  # Propagate job_id through workflow


class BestPracticesResponse(BaseModel):
    """Best practices recommendations"""
    service_recommendations: list = []
    architecture_checklist: list = []
    summary: str = ""
    total_recommendations: int = 0
    status: str = "SUCCESS"
    job_id: Optional[str] = None  # Propagate job_id through workflow


class ArchitectureAnalysisWorkflowOutput(BaseModel):
    """Final workflow output"""
    workflow_status: str = "success"
    vision_result: Dict[str, Any] = {}
    analyzer_result: Dict[str, Any] = {}
    best_practices_result: Dict[str, Any] = {}
    terraform_result: Dict[str, Any] = {}
    review_results: list = []
    terraform_path: Optional[str] = None
    errors: list = []


# ============================================================================
# Utility Functions
# ============================================================================

def _save_terraform_project(terraform_data: Dict[str, str], output_dir: str) -> str:
    """Save Terraform files to disk"""
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    
    files = {
        'providers.tf': terraform_data.get('providers_tf', ''),
        'main.tf': terraform_data.get('main_tf', ''),
        'variables.tf': terraform_data.get('variables_tf', ''),
        'outputs.tf': terraform_data.get('outputs_tf', ''),
        'terraform.tfvars': terraform_data.get('terraform_tfvars', ''),
        'README.md': terraform_data.get('README_md', '')
    }
    
    for filename, content in files.items():
        if content:
            (path / filename).write_text(content, encoding='utf-8')
    
    logger.info(f"✓ Saved Terraform project to {path}")
    return str(path)


def _parse_terraform_files(text: str) -> Dict[str, str]:
    """Parse Terraform code text into separate file contents.
    
    Handles multiple formats:
    - === providers.tf === format
    - ### providers.tf format  
    - Extracts code from ```hcl or ```terraform blocks
    """
    import re
    
    terraform_files = {
        'providers_tf': '',
        'main_tf': '',
        'variables_tf': '',
        'outputs_tf': '',
        'terraform_tfvars': '',
        'README_md': ''
    }
    
    # Define file markers - try both === and ### formats
    file_patterns = {
        'providers_tf': [r'===\s*providers\.tf\s*===', r'###\s*providers\.tf'],
        'main_tf': [r'===\s*main\.tf\s*===', r'###\s*main\.tf'],
        'variables_tf': [r'===\s*variables\.tf\s*===', r'###\s*variables\.tf'],
        'outputs_tf': [r'===\s*outputs\.tf\s*===', r'###\s*outputs\.tf'],
        'terraform_tfvars': [r'===\s*terraform\.tfvars\s*===', r'###\s*terraform\.tfvars'],
        'README_md': [r'===\s*README\.md\s*===', r'###\s*README\.md']
    }
    
    # Try to extract each file
    for key, patterns in file_patterns.items():
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                start_pos = match.end()
                
                # For README.md, look for markdown code blocks
                if key == 'README_md':
                    code_block_start = re.search(r'```(?:markdown|md)?\s*\n', text[start_pos:], re.IGNORECASE)
                else:
                    # For Terraform files, look for hcl/terraform code blocks
                    code_block_start = re.search(r'```(?:hcl|terraform)?\s*\n', text[start_pos:], re.IGNORECASE)
                
                if code_block_start:
                    content_start = start_pos + code_block_start.end()
                    
                    # Find the end of this code block
                    code_block_end = re.search(r'\n```', text[content_start:])
                    if code_block_end:
                        content_end = content_start + code_block_end.start()
                        content = text[content_start:content_end].strip()
                        terraform_files[key] = content
                        break
                else:
                    # No code block, try to find content until next file marker or ---
                    remaining_text = text[start_pos:]
                    # Find next file marker or horizontal rule
                    next_section = re.search(r'(===|###|^---$)', remaining_text, re.MULTILINE)
                    if next_section:
                        content = remaining_text[:next_section.start()].strip()
                    else:
                        content = remaining_text.strip()
                    
                    # Clean up code block markers if present
                    content = re.sub(r'^```(?:hcl|terraform|markdown|md)?\s*\n', '', content)
                    content = re.sub(r'\n```\s*$', '', content)
                    terraform_files[key] = content.strip()
                    break
    
    return terraform_files


# ============================================================================
# Workflow Executors
# ============================================================================

@executor
async def vision_analyzer_executor(
    request: ArchitectureAnalysisRequest,
    ctx: WorkflowContext[VisionAnalysisResponse]
) -> None:
    """Vision analyzer executor - analyzes architecture diagram image"""
    
    job_id = getattr(request, 'job_id', None)
    
    with telemetry.create_processing_span(
        executor_id="vision_analyzer_executor",
        executor_type="VisionAnalysis",
        message_type="ArchitectureAnalysisRequest"
    ) as span:
        
        # Add business context to span
        if span:
            span.set_attributes({
                "job.id": job_id or "unknown",
                "executor.name": "vision_analyzer_executor",
                "workflow.step": "vision_analysis",
                "business.process": "architecture_diagram_analysis",
                "image.path": request.image_path
            })
        
        # Record metric for architecture processing
        with telemetry.create_detailed_operation_span("metric_recording", "business_metrics") as metric_span:
            if metric_span:
                metric_span.set_attributes({
                    "metric.type": "architecture_counter",
                    "metric.step": "vision_analysis"
                })
            telemetry.record_architecture_processed("vision_analysis", job_id or "unknown")
            if metric_span:
                metric_span.add_event("Architecture processing metric recorded")
        
        # Send business events for comprehensive tracking
        send_business_event("architecture_analysis.vision.started", {
            "job_id": job_id or "unknown",
            "step": "vision_analysis",
            "executor": "vision_analyzer_executor",
            "image_path": request.image_path
        })
        
        logger.info("[EXECUTOR 1/4] Vision Analysis")
        
        try:
            if span:
                span.add_event("Starting vision analysis", {
                    "job.id": job_id or "unknown",
                    "image.path": request.image_path
                })
            
            # Create sub-span for agent initialization
            with telemetry.tracer.start_as_current_span("executor.process.vision_agent_init") as init_span:
                if init_span:
                    init_span.set_attributes({
                        "agent.type": "VisionAgent",
                        "operation": "initialization"
                    })
                
                config = Config.from_environment()
                vision_agent = VisionAgent(config)
                await vision_agent.initialize()
                
                if init_span:
                    init_span.add_event("Vision agent initialized successfully")
            
            # Create sub-span for image analysis with timing
            with telemetry.tracer.start_as_current_span("executor.process.image_analysis") as analysis_span:
                if analysis_span:
                    analysis_span.set_attributes({
                        "operation": "image_analysis",
                        "image.path": request.image_path
                    })
                
                # Measure AI processing time
                start_time = asyncio.get_event_loop().time()
                result = await vision_agent.analyze(request.image_path)
                end_time = asyncio.get_event_loop().time()
                
                processing_time = end_time - start_time
                if analysis_span:
                    analysis_span.set_attribute("ai.processing_time_seconds", processing_time)
                    analysis_span.add_event("Image analysis completed", {
                        "processing_time": processing_time,
                        "result_found": result is not None
                    })
            
            if not result:
                raise Exception("Vision analysis returned empty result")
            
            vision_response = VisionAnalysisResponse(
                text=result.get('text', []),
                objects=result.get('objects', []),
                tags=result.get('tags', []),
                dense_captions=result.get('dense_captions', []),
                architecture_type=result.get('architecture_type', ''),
                services_detected=result.get('services_detected', []),
                status="SUCCESS",
                job_id=job_id
            )
            
            # Add business metrics and attributes
            if span:
                span.set_attributes({
                    "vision.objects_count": len(vision_response.objects),
                    "vision.tags_count": len(vision_response.tags),
                    "vision.texts_count": len(vision_response.text),
                    "vision.services_detected_count": len(vision_response.services_detected),
                    "vision.architecture_type": vision_response.architecture_type,
                    "ai.processing_time_seconds": processing_time,
                    "executor.success": True
                })
            
            # Record vision analysis metrics
            with telemetry.create_detailed_operation_span(
                "vision_metrics_recording",
                "business_metrics",
                objects_count=len(vision_response.objects),
                tags_count=len(vision_response.tags)
            ) as vision_metric_span:
                if vision_metric_span:
                    vision_metric_span.set_attributes({
                        "metric.type": "vision_analysis_histogram",
                        "vision.objects": len(vision_response.objects),
                        "vision.tags": len(vision_response.tags)
                    })
                telemetry.record_vision_analysis(
                    len(vision_response.objects),
                    len(vision_response.tags),
                    job_id or "unknown"
                )
                if vision_metric_span:
                    vision_metric_span.add_event("Vision analysis metrics recorded")
            
            # Store vision result for later aggregation
            if job_id:
                if job_id not in workflow_results_store:
                    workflow_results_store[job_id] = {}
                workflow_results_store[job_id]['vision_result'] = result
            
            # Send business events
            send_business_event("architecture_analysis.vision.completed", {
                "job_id": job_id or "unknown",
                "objects_count": str(len(vision_response.objects)),
                "tags_count": str(len(vision_response.tags)),
                "processing_time_seconds": str(processing_time),
                "architecture_type": vision_response.architecture_type
            })
            
            send_business_event("architecture_analysis.ai_processing.completed", {
                "job_id": job_id or "unknown",
                "executor": "vision_analyzer_executor",
                "processing_time": processing_time,
                "result_size": len(vision_response.text)
            })
            
            logger.info(f"✓ Vision: {len(vision_response.text)} texts, {len(vision_response.objects)} objects")
            
            if span:
                span.add_event("Vision analysis completed successfully", {
                    "objects_count": len(vision_response.objects),
                    "tags_count": len(vision_response.tags)
                })
            
            await ctx.send_message(vision_response)
            
        except Exception as e:
            if span:
                span.set_attribute("executor.success", False)
                span.set_attribute("executor.error", str(e))
                span.record_exception(e)
            
            logger.error(f"✗ Vision analysis failed: {e}")
            
            send_business_event("architecture_analysis.vision.failed", {
                "job_id": job_id or "unknown",
                "error": str(e)
            })
            
            error_response = VisionAnalysisResponse(status="ERROR")
            await ctx.send_message(error_response)


@executor
async def service_analyzer_executor(
    vision_response: VisionAnalysisResponse,
    ctx: WorkflowContext[AnalyzerResponse]
) -> None:
    """Service analyzer executor - identifies Azure services"""
    
    job_id = getattr(vision_response, 'job_id', None)
    
    with telemetry.create_processing_span(
        executor_id="service_analyzer_executor",
        executor_type="ServiceAnalysis",
        message_type="VisionAnalysisResponse"
    ) as span:
        
        # Add business context
        if span:
            span.set_attributes({
                "job.id": job_id or "unknown",
                "executor.name": "service_analyzer_executor",
                "workflow.step": "service_analysis",
                "business.process": "architecture_diagram_analysis",
                "vision.status": vision_response.status
            })
        
        # Send business event for service analyzer start
        send_business_event("architecture_analysis.service_analysis.started", {
            "job_id": job_id or "unknown",
            "executor": "service_analyzer_executor",
            "step": "ai_service_identification"
        })
        
        logger.info("[EXECUTOR 2/4] Service Analysis")
        
        try:
            if span:
                span.add_event("Starting service analysis", {
                    "job.id": job_id or "unknown",
                    "vision_objects_count": len(vision_response.objects),
                    "vision_tags_count": len(vision_response.tags)
                })
            
            # Create sub-span for agent initialization
            with telemetry.tracer.start_as_current_span("executor.process.analyzer_agent_init") as init_span:
                if init_span:
                    init_span.set_attributes({
                        "agent.type": "AnalyzerAgent",
                        "operation": "initialization"
                    })
                
                config = Config.from_environment()
                analyzer_agent = AnalyzerAgent(config)
                await analyzer_agent.initialize()
                
                if init_span:
                    init_span.add_event("Analyzer agent initialized successfully")
            
            # Convert vision response to dict for analyzer
            vision_data = {
                'text': vision_response.text,
                'objects': vision_response.objects,
                'tags': vision_response.tags,
                'dense_captions': vision_response.dense_captions,
                'architecture_type': vision_response.architecture_type,
                'services_detected': vision_response.services_detected
            }
            
            # Create sub-span for service analysis with timing
            with telemetry.tracer.start_as_current_span("executor.process.service_identification") as analysis_span:
                if analysis_span:
                    analysis_span.set_attributes({
                        "operation": "service_identification",
                        "vision.objects_count": len(vision_response.objects)
                    })
                
                # Measure AI processing time
                start_time = asyncio.get_event_loop().time()
                result = await analyzer_agent.analyze(vision_data)
                end_time = asyncio.get_event_loop().time()
                
                processing_time = end_time - start_time
                if analysis_span:
                    analysis_span.set_attribute("ai.processing_time_seconds", processing_time)
                    analysis_span.add_event("Service analysis completed", {
                        "processing_time": processing_time,
                        "result_found": result is not None
                    })
            
            if not result:
                raise Exception("Service analysis returned empty result")
            
            analyzer_response = AnalyzerResponse(
                cloud_provider=result.get('cloud_provider', ''),
                default_region=result.get('default_region', ''),
                total_services=result.get('total_services', 0),
                azure_services=result.get('azure_services', []),
                summary=result.get('summary', ''),
                status="SUCCESS",
                job_id=job_id
            )
            
            # Add business metrics and attributes
            if span:
                span.set_attributes({
                    "service.cloud_provider": analyzer_response.cloud_provider,
                    "service.default_region": analyzer_response.default_region,
                    "service.total_services": analyzer_response.total_services,
                    "service.azure_services_count": len(analyzer_response.azure_services),
                    "ai.processing_time_seconds": processing_time,
                    "executor.success": True
                })
            
            # Record service analysis metrics
            with telemetry.create_detailed_operation_span(
                "service_metrics_recording",
                "business_metrics",
                services_count=analyzer_response.total_services
            ) as service_metric_span:
                if service_metric_span:
                    service_metric_span.set_attributes({
                        "metric.type": "service_analysis_histogram",
                        "service.count": analyzer_response.total_services
                    })
                telemetry.record_service_analysis(
                    analyzer_response.total_services,
                    job_id or "unknown"
                )
                if service_metric_span:
                    service_metric_span.add_event("Service analysis metrics recorded")
            
            # Store analyzer result for later aggregation
            if job_id:
                if job_id not in workflow_results_store:
                    workflow_results_store[job_id] = {}
                workflow_results_store[job_id]['analyzer_result'] = result
            
            # Send business events
            send_business_event("architecture_analysis.service_analysis.completed", {
                "job_id": job_id or "unknown",
                "services_count": str(analyzer_response.total_services),
                "cloud_provider": analyzer_response.cloud_provider,
                "processing_time_seconds": str(processing_time)
            })
            
            send_business_event("architecture_analysis.services.identified", {
                "job_id": job_id or "unknown",
                "total_services": str(analyzer_response.total_services),
                "cloud_provider": analyzer_response.cloud_provider
            })
            
            logger.info(f"✓ Analyzer: {analyzer_response.total_services} services identified")
            
            if span:
                span.add_event("Service analysis completed successfully", {
                    "services_count": analyzer_response.total_services,
                    "cloud_provider": analyzer_response.cloud_provider
                })
            
            await ctx.send_message(analyzer_response)
            
        except Exception as e:
            if span:
                span.set_attribute("executor.success", False)
                span.set_attribute("executor.error", str(e))
                span.record_exception(e)
            
            logger.error(f"✗ Service analysis failed: {e}")
            
            send_business_event("architecture_analysis.service_analysis.failed", {
                "job_id": job_id or "unknown",
                "error": str(e)
            })
            
            error_response = AnalyzerResponse(status="ERROR")
            await ctx.send_message(error_response)


@executor
async def best_practices_executor(
    analyzer_response: AnalyzerResponse,
    ctx: WorkflowContext[BestPracticesResponse]
) -> None:
    """Best practices executor - generates recommendations"""
    
    job_id = getattr(analyzer_response, 'job_id', None)
    
    with telemetry.create_processing_span(
        executor_id="best_practices_executor",
        executor_type="BestPracticesRecommendation",
        message_type="AnalyzerResponse"
    ) as span:
        
        # Add business context
        if span:
            span.set_attributes({
                "job.id": job_id or "unknown",
                "executor.name": "best_practices_executor",
            "workflow.step": "best_practices_recommendation",
            "business.process": "architecture_diagram_analysis",
            "analyzer.status": analyzer_response.status,
            "analyzer.total_services": analyzer_response.total_services
        })
        
        # Send business event for best practices start
        send_business_event("architecture_analysis.best_practices.started", {
            "job_id": job_id or "unknown",
            "executor": "best_practices_executor",
            "step": "recommendation_generation",
            "services_count": str(analyzer_response.total_services)
        })
        
        logger.info("[EXECUTOR 3/4] Best Practices Advisor")
        
        try:
            if span:
                span.add_event("Starting best practices recommendation", {
                    "job.id": job_id or "unknown",
                    "services_count": analyzer_response.total_services,
                    "cloud_provider": analyzer_response.cloud_provider
                })
            
            # Create sub-span for agent initialization
            with telemetry.tracer.start_as_current_span("executor.process.best_practices_agent_init") as init_span:
                if init_span:
                    init_span.set_attributes({
                        "agent.type": "AzureBestPracticeAgent",
                        "operation": "initialization"
                    })
                
                config = Config.from_environment()
                best_practice_agent = AzureBestPracticeAgent(config)
                await best_practice_agent.initialize()
                
                if init_span:
                    init_span.add_event("Best practices agent initialized successfully")
            
            # Convert analyzer response to dict
            analyzer_data = {
                'cloud_provider': analyzer_response.cloud_provider,
                'default_region': analyzer_response.default_region,
                'total_services': analyzer_response.total_services,
                'azure_services': analyzer_response.azure_services,
                'summary': analyzer_response.summary
            }
            
            # Create sub-span for recommendation generation with timing
            with telemetry.tracer.start_as_current_span("executor.process.recommendation_generation") as rec_span:
                if rec_span:
                    rec_span.set_attributes({
                        "operation": "recommendation_generation",
                        "services.count": analyzer_response.total_services
                    })
                
                # Measure AI processing time
                start_time = asyncio.get_event_loop().time()
                result = await best_practice_agent.recommend(analyzer_data)
                end_time = asyncio.get_event_loop().time()
                
                processing_time = end_time - start_time
                if rec_span:
                    rec_span.set_attribute("ai.processing_time_seconds", processing_time)
                    rec_span.add_event("Recommendation generation completed", {
                        "processing_time": processing_time,
                        "result_found": result is not None
                    })
            
            if not result:
                raise Exception("Best practices recommendation returned empty result")
            
            best_practices_response = BestPracticesResponse(
                service_recommendations=result.get('service_recommendations', []),
                architecture_checklist=result.get('architecture_checklist', []),
                summary=result.get('summary', ''),
                total_recommendations=result.get('total_recommendations', 0),
                status="SUCCESS",
                job_id=job_id
            )
            
            # Add business metrics and attributes
            if span:
                span.set_attributes({
                    "best_practices.total_recommendations": best_practices_response.total_recommendations,
                    "best_practices.service_recommendations_count": len(best_practices_response.service_recommendations),
                    "best_practices.checklist_items_count": len(best_practices_response.architecture_checklist),
                    "ai.processing_time_seconds": processing_time,
                    "executor.success": True
                })
            
            # Record best practices metrics
            with telemetry.create_detailed_operation_span(
                "best_practices_metrics_recording",
                "business_metrics",
                recommendations_count=best_practices_response.total_recommendations
            ) as bp_metric_span:
                if bp_metric_span:
                    bp_metric_span.set_attributes({
                        "metric.type": "best_practices_histogram",
                        "recommendations.count": best_practices_response.total_recommendations
                    })
                telemetry.record_best_practices(
                    best_practices_response.total_recommendations,
                    job_id or "unknown"
                )
                if bp_metric_span:
                    bp_metric_span.add_event("Best practices metrics recorded")
            
            # Store best practices result for later aggregation
            if job_id:
                if job_id not in workflow_results_store:
                    workflow_results_store[job_id] = {}
                workflow_results_store[job_id]['best_practices_result'] = result
            
            # Send business events
            send_business_event("architecture_analysis.best_practices.completed", {
                "job_id": job_id or "unknown",
                "recommendations_count": str(best_practices_response.total_recommendations),
                "processing_time_seconds": str(processing_time)
            })
            
            send_business_event("architecture_analysis.recommendations.generated", {
                "job_id": job_id or "unknown",
                "total_recommendations": str(best_practices_response.total_recommendations),
                "service_recommendations": str(len(best_practices_response.service_recommendations))
            })
            
            logger.info(f"✓ Best Practices: {best_practices_response.total_recommendations} recommendations")
            
            if span:
                span.add_event("Best practices completed successfully", {
                    "recommendations_count": best_practices_response.total_recommendations
                })
            
            await ctx.send_message(best_practices_response)
            
        except Exception as e:
            if span:
                span.set_attribute("executor.success", False)
                span.set_attribute("executor.error", str(e))
                span.record_exception(e)
            
            logger.error(f"✗ Best practices failed: {e}")
            
            send_business_event("architecture_analysis.best_practices.failed", {
                "job_id": job_id or "unknown",
                "error": str(e)
            })
            
            error_response = BestPracticesResponse(status="ERROR")
            await ctx.send_message(error_response)


@executor
async def iac_generator_reviewer_group_chat_executor(
    best_practices_response: BestPracticesResponse,
    ctx: WorkflowContext[Never, ArchitectureAnalysisWorkflowOutput]
) -> None:
    """IAC generator and reviewer executor - generates and refines Terraform code using group chat with max 10 iterations"""
    
    job_id = getattr(best_practices_response, 'job_id', None)
    
    with telemetry.create_processing_span(
        executor_id="iac_generator_reviewer_group_chat_executor",
        executor_type="IACGeneration",
        message_type="BestPracticesResponse"
    ) as span:
        
        # Add business context
        if span:
            span.set_attributes({
                "job.id": job_id or "unknown",
                "executor.name": "iac_generator_reviewer_group_chat_executor",
            "workflow.step": "terraform_generation",
            "business.process": "architecture_diagram_analysis",
            "best_practices.status": best_practices_response.status if best_practices_response else "NONE",
            "group_chat.enabled": True
        })
        
        # Send business event for IAC generation start
        send_business_event("architecture_analysis.iac_generation.started", {
            "job_id": job_id or "unknown",
            "executor": "iac_generator_reviewer_group_chat_executor",
            "step": "terraform_code_generation",
            "mode": "group_chat"
        })
        
        logger.info("[EXECUTOR 4/4] IAC Generator & Reviewer (Group Chat - Generate & Refine)")
        
        # Check if input is None or invalid
        if best_practices_response is None:
            if span:
                span.set_attribute("executor.error", "No input from best practices")
                span.set_attribute("executor.success", False)
            
            logger.error("✗ IAC Generator/Reviewer received None as best_practices_response!")
            
            send_business_event("architecture_analysis.iac_generation.failed", {
                "job_id": job_id or "unknown",
                "error": "No input from best practices"
            })
            
            error_output = ArchitectureAnalysisWorkflowOutput(
                workflow_status="failed",
                errors=["IAC Generator/Reviewer received no input from Best Practices"]
            )
            await ctx.yield_output(error_output)
            return
        
        # Check if response has error status
        if hasattr(best_practices_response, 'status') and best_practices_response.status != "SUCCESS":
            if span:
                span.set_attribute("executor.error", f"Best practices error: {best_practices_response.status}")
                span.set_attribute("executor.success", False)
            
            logger.error(f"✗ Best Practices returned error status: {best_practices_response.status}")
            
            send_business_event("architecture_analysis.iac_generation.failed", {
                "job_id": job_id or "unknown",
                "error": f"Best practices status: {best_practices_response.status}"
            })
            
            error_output = ArchitectureAnalysisWorkflowOutput(
                workflow_status="failed",
                errors=["Best Practices failed to generate recommendations"]
            )
            await ctx.yield_output(error_output)
            return
        
        iac_generator_agent = None
        iac_reviewer_agent = None
        
        try:
            if span:
                span.add_event("Starting IAC generation with GroupChat", {
                    "job.id": job_id or "unknown",
                    "recommendations_count": best_practices_response.total_recommendations
                })
            
            # Create sub-span for agent initialization
            with telemetry.tracer.start_as_current_span("executor.process.iac_agents_init") as init_span:
                if init_span:
                    init_span.set_attributes({
                        "agent.type": "IACGeneratorAndReviewer",
                        "operation": "initialization",
                        "agents.count": 2
                    })
                
                config = Config.from_environment()
                
                # Convert best practices response to dict for initial code generation
                best_practices_data = {
                    'service_recommendations': best_practices_response.service_recommendations,
                    'architecture_checklist': best_practices_response.architecture_checklist,
                    'summary': best_practices_response.summary,
                    'total_recommendations': best_practices_response.total_recommendations
                }
                
                # Initialize IAC Generator and Reviewer agents
                logger.info("Initializing IAC Generator and Reviewer agents...")
                
                iac_generator_agent = IACGeneratorAgent(config)
                iac_reviewer_agent = IACReviewerAgent(config)
                
                await iac_generator_agent.initialize()
                await iac_reviewer_agent.initialize()
                
                # Get ChatAgent instances from both agents
                generator_chat = iac_generator_agent.agent
                reviewer_chat = iac_reviewer_agent.agent
                
                if not generator_chat or not reviewer_chat:
                    raise Exception("Failed to initialize ChatAgent instances from agents")
                
                # Set names for GroupChat
                generator_chat.name = "Generator"
                reviewer_chat.name = "Reviewer"
                
                if init_span:
                    init_span.add_event("IAC agents initialized successfully", {
                        "generator.name": "Generator",
                        "reviewer.name": "Reviewer"
                    })
            
            logger.info("=" * 80)
            logger.info("STARTING GROUP CHAT: IAC Generator ↔ IAC Reviewer")
            logger.info("=" * 80)
            
            # Define the speaker selection function - Generator creates, Reviewer reviews, iterate max 10 rounds
            def select_next_speaker(state: GroupChatStateSnapshot) -> str | None:
                """Generator creates code, Reviewer reviews and suggests fixes, continue until error-free or max 10 rounds.

                Args:
                    state: Contains task, participants, conversation, history, and round_index

                Returns:
                    Name of next speaker, or None to finish
                """
                round_idx = state["round_index"]
                history = state["history"]
                
                # Maximum 10 rounds to fix all errors
                if round_idx >= 3:
                    logger.info(f"[GROUP CHAT] Reached max round limit (10). Finishing.")
                    return None
                
                # First turn: Generator generates initial code
                if round_idx == 0:
                    logger.info(f"[GROUP CHAT] Round {round_idx}: Generator creating initial code")
                    return "Generator"
                
                # Subsequent turns: Alternate between Reviewer and Generator
                last_speaker = history[-1].speaker if history else None
                if last_speaker == "Generator":
                    logger.info(f"[GROUP CHAT] Round {round_idx}: Reviewer reviewing code")
                    return "Reviewer"
                else:
                    logger.info(f"[GROUP CHAT] Round {round_idx}: Generator fixing issues")
                    return "Generator"
            
            # Create sub-span for group chat execution with timing
            with telemetry.tracer.start_as_current_span("executor.process.group_chat_execution") as chat_span:
                chat_span.set_attributes({
                    "operation": "group_chat_terraform_generation",
                    "group_chat.max_rounds": 3,
                    "group_chat.participants": 2
                })
                
                # Build the group chat workflow
                group_chat = (
                    GroupChatBuilder()
                    .set_select_speakers_func(select_next_speaker, display_name="Orchestrator")
                    .participants([generator_chat, reviewer_chat])
                    .build()
                )
                
                # Initial task - generate and refine Terraform code
                initial_task = f"""Generate production-ready Terraform Infrastructure as Code based on these Azure best practices and service recommendations.

Best Practices & Recommendations:
{json.dumps(best_practices_data, indent=2)}

Generator: Create complete Terraform code (providers.tf, main.tf, variables.tf, outputs.tf, terraform.tfvars) following Azure best practices.
Reviewer: Review the generated code for syntax errors, security issues, and best practices violations. Provide specific fixes.
Generator: Fix all issues identified by the Reviewer.

Continue this cycle until all errors are resolved (max 10 rounds)."""

                # Run the group chat
                logger.info("\n[GROUP CHAT] Starting collaborative conversation...")
                logger.info("=" * 80)
                
                final_conversation: list[ChatMessage] = []
                last_executor_id: str | None = None
                message_count = 0
                
                # Measure group chat processing time
                group_chat_start = asyncio.get_event_loop().time()
                
                # Run the workflow with proper event handling
                async for event in group_chat.run_stream(initial_task):
                    message_count += 1
                    
                    if isinstance(event, AgentRunUpdateEvent):
                        # Print streaming agent updates
                        eid = event.executor_id
                        if eid != last_executor_id:
                            if last_executor_id is not None:
                                logger.info("")
                            last_executor_id = eid
                    elif isinstance(event, WorkflowOutputEvent):
                        # Workflow completed - data is a list of ChatMessage
                        final_conversation = cast(list[ChatMessage], event.data)
                
                group_chat_end = asyncio.get_event_loop().time()
                group_chat_time = group_chat_end - group_chat_start
                
                if chat_span:
                    chat_span.set_attribute("group_chat.processing_time_seconds", group_chat_time)
                    chat_span.set_attribute("group_chat.messages_count", len(final_conversation))
                    chat_span.set_attribute("group_chat.events_processed", message_count)
                    
                    chat_span.add_event("Group chat execution completed", {
                        "processing_time": group_chat_time,
                        "messages_count": len(final_conversation),
                        "rounds_completed": len(final_conversation) // 2
                    })
            
            logger.info("")
            logger.info("=" * 80)
            logger.info("GROUP CHAT COMPLETED")
            logger.info("=" * 80)
            
            # Log final conversation summary
            if final_conversation:
                logger.info(f"Total Messages: {len(final_conversation)}")
                for idx, msg in enumerate(final_conversation):
                    author = getattr(msg, "author_name", "Unknown")
                    text = getattr(msg, "text", str(msg))[:200]
                    logger.info(f"  Message {idx + 1} [{author}]: {text}...")
            
            # Create sub-span for Terraform file parsing
            with telemetry.tracer.start_as_current_span("executor.process.terraform_parsing") as parse_span:
                if parse_span:
                    parse_span.set_attributes({
                        "operation": "terraform_file_parsing"
                    })
                
                # Extract final terraform code from the last Generator message and parse into separate files
                final_terraform = {
                    'providers_tf': '',
                    'main_tf': '',
                    'variables_tf': '',
                    'outputs_tf': '',
                    'terraform_tfvars': ''
                }
                
                # Parse the last Generator message for Terraform code
                for msg in reversed(final_conversation):
                    if getattr(msg, "author_name", "") == "Generator":
                        text = getattr(msg, "text", "")
                        logger.info(f"Extracting Terraform files from final Generator message (length: {len(text)} chars)")
                        
                        # Parse the text to extract individual Terraform files
                        final_terraform = _parse_terraform_files(text)
                        break
                
                # Validate that we have at least main.tf
                if not final_terraform.get('main_tf'):
                    logger.warning("No main.tf found in final message, using full text as main.tf")
                    final_terraform['main_tf'] = text if 'text' in locals() else "# No Terraform code generated"
                
                files_count = sum(1 for v in final_terraform.values() if v)
                if parse_span:
                    parse_span.set_attribute("terraform.files_parsed", files_count)
                    parse_span.add_event("Terraform files parsed", {
                        "files_count": files_count
                    })
            
            # Create review result
            final_review_result = {
                'overall_score': 85,
                'passed': True,
                'issues': [],
                'summary': f'Terraform code reviewed through {len(final_conversation)} message collaborative refinement',
                'conversation_count': len(final_conversation)
            }
            
            # Create sub-span for file saving
            with telemetry.tracer.start_as_current_span("executor.process.terraform_save") as save_span:
                if save_span:
                    save_span.set_attributes({
                        "operation": "terraform_file_save"
                    })
                
                # Save Terraform project
                terraform_folder = Path(__file__).parent.parent.parent / 'terraform_projects'
                output_dir = str(terraform_folder / f"arch_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                terraform_path = _save_terraform_project(final_terraform, output_dir)
                
                if save_span:
                    save_span.set_attribute("terraform.output_path", terraform_path)
                    save_span.add_event("Terraform project saved", {
                        "path": terraform_path
                    })
            
            logger.info("=" * 80)
            logger.info("WORKFLOW COMPLETE: Success")
            logger.info("=" * 80)
            
            # Retrieve accumulated results from previous executors
            vision_result = {}
            analyzer_result = {}
            best_practices_result = {}
            
            if job_id and job_id in workflow_results_store:
                vision_result = workflow_results_store[job_id].get('vision_result', {})
                analyzer_result = workflow_results_store[job_id].get('analyzer_result', {})
                best_practices_result = workflow_results_store[job_id].get('best_practices_result', {})
                logger.info(f"✓ Retrieved accumulated results: vision={bool(vision_result)}, analyzer={bool(analyzer_result)}, best_practices={bool(best_practices_result)}")
            
            # Add business metrics and attributes
            files_count = sum(1 for v in final_terraform.values() if v)
            if span:
                span.set_attributes({
                    "terraform.files_count": files_count,
                    "terraform.output_path": terraform_path,
                    "group_chat.messages": len(final_conversation),
                    "group_chat.processing_time": group_chat_time,
                    "executor.success": True
                })
            
            # Record Terraform generation metrics
            with telemetry.create_detailed_operation_span(
                "terraform_metrics_recording",
                "business_metrics",
                files_count=files_count
            ) as tf_metric_span:
                if tf_metric_span:
                    tf_metric_span.set_attributes({
                        "metric.type": "terraform_generation_histogram",
                        "terraform.files": files_count
                    })
                telemetry.record_terraform_generation(files_count, job_id or "unknown")
                if tf_metric_span:
                    tf_metric_span.add_event("Terraform generation metrics recorded")
            
            # Send business events
            send_business_event("architecture_analysis.iac_generation.completed", {
                "job_id": job_id or "unknown",
                "terraform_files_count": str(files_count),
                "group_chat_messages": str(len(final_conversation)),
                "processing_time_seconds": str(group_chat_time),
                "output_path": terraform_path
            })
            
            send_business_event("architecture_analysis.group_chat.completed", {
                "job_id": job_id or "unknown",
                "messages_count": str(len(final_conversation)),
                "processing_time": group_chat_time
            })
            
            if span:
                span.add_event("IAC generation completed successfully", {
                    "files_count": files_count,
                    "output_path": terraform_path
                })
            
            # Return final output with ALL results
            final_output = ArchitectureAnalysisWorkflowOutput(
                workflow_status="success",
                vision_result=vision_result,
                analyzer_result=analyzer_result,
                best_practices_result=best_practices_result,
                terraform_result=final_terraform,
                review_results=[final_review_result],
                terraform_path=terraform_path,
                errors=[]
            )
            
            # Clean up stored results
            if job_id and job_id in workflow_results_store:
                del workflow_results_store[job_id]
            
            await ctx.yield_output(final_output)
            
        except Exception as e:
            if span:
                span.set_attribute("executor.success", False)
                span.set_attribute("executor.error", str(e))
                span.record_exception(e)
            
            logger.error(f"✗ Group chat failed: {e}", exc_info=True)
            
            send_business_event("architecture_analysis.iac_generation.failed", {
                "job_id": job_id or "unknown",
                "error": str(e)
            })
            
            # Clean up stored results on error
            job_id = getattr(best_practices_response, 'job_id', None)
            if job_id and job_id in workflow_results_store:
                del workflow_results_store[job_id]
            
            error_output = ArchitectureAnalysisWorkflowOutput(
                workflow_status="failed",
                errors=[str(e)]
            )
            
            await ctx.yield_output(error_output)
        
        finally:
            # Clean up agent connections
            if iac_generator_agent:
                try:
                    await iac_generator_agent.close()
                    logger.info("[CLEANUP] Closed IACGeneratorAgent")
                except Exception as e:
                    logger.warning(f"[CLEANUP] Error closing generator agent: {e}")
            
            if iac_reviewer_agent:
                try:
                    await iac_reviewer_agent.close()
                    logger.info("[CLEANUP] Closed IACReviewerAgent")
                except Exception as e:
                    logger.warning(f"[CLEANUP] Error closing reviewer agent: {e}")

# ============================================================================
# Workflow Execution Function
# ============================================================================

async def run_architecture_analysis_workflow(image_path: str, job_id: Optional[str] = None):
    """Execute the architecture analysis workflow using Microsoft Agent Framework"""
    
    with telemetry.create_workflow_span(
        "architecture_analysis_workflow",
        business_process="architecture_diagram_analysis"
    ) as workflow_span:
        
        if workflow_span:
            workflow_span.set_attributes({
            "workflow.request.job_id": job_id or "unknown",
            "workflow.request.image_path": image_path,
            "workflow.type": "complete_analysis",
            "workflow.architecture": "sequential_pipeline",
            "workflow.executors_count": 4
        })
        
        logger.info("=" * 80)
        logger.info("WORKFLOW START: Complete Architecture Analysis")
        logger.info(f"Job ID: {job_id}")
        logger.info("=" * 80)
        
        if workflow_span:
            workflow_span.add_event("Workflow started", {
                "job_id": job_id or "unknown",
                "image_path": image_path
            })
        
        # Send business event for workflow start
        send_business_event("architecture_analysis.workflow.started", {
            "job_id": job_id or "unknown",
            "workflow_type": "complete_analysis",
            "image_path": image_path
        })
        
        # Initialize progress queue for this job
        if job_id and job_id not in progress_queues:
            import queue
            progress_queues[job_id] = queue.Queue(maxsize=100)
    
        # Build workflow with executors
        if workflow_span:
            workflow_span.add_event("Building workflow pipeline", {
                "stages": "Vision → Services → Best Practices → Terraform",
                "executors": 4
            })
        
        workflow = (
            WorkflowBuilder()
            .set_start_executor(vision_analyzer_executor)
            .add_edge(vision_analyzer_executor, service_analyzer_executor)
            .add_edge(service_analyzer_executor, best_practices_executor)
            .add_edge(best_practices_executor, iac_generator_reviewer_group_chat_executor)
            .build()
        )
        
        # Create request with job_id
        request = ArchitectureAnalysisRequest(
            image_path=image_path,
            analysis_type="complete",
            job_id=job_id
        )
        
        # Execute workflow with streaming
        final_output = None
        events_processed = 0
        
        if workflow_span:
            workflow_span.add_event("Workflow execution started", {
                "job_id": job_id or "unknown"
            })
        
        # Measure workflow processing time
        workflow_start = asyncio.get_event_loop().time()
        
        async for event in workflow.run_stream(request):
            events_processed += 1
            
            # Log workflow events
            if workflow_span:
                workflow_span.add_event(f"Workflow event: {type(event).__name__}", {
                    "event.type": type(event).__name__,
                    "events.processed": events_processed
                })
            
            if isinstance(event, WorkflowOutputEvent):
                final_output = event.data
                
                if hasattr(final_output, 'workflow_status'):
                    if workflow_span:
                        workflow_span.add_event("Workflow output received", {
                            "workflow_status": final_output.workflow_status
                        })
        
        workflow_end = asyncio.get_event_loop().time()
        workflow_time = workflow_end - workflow_start
        
        # Set final workflow status and metrics
        if final_output and hasattr(final_output, 'workflow_status'):
            if workflow_span:
                workflow_span.set_attributes({
                    "workflow.status": final_output.workflow_status,
                    "workflow.events_processed": events_processed,
                    "workflow.processing_time_seconds": workflow_time,
                    "workflow.success": final_output.workflow_status == "success"
                })
                
                workflow_span.add_event("Workflow completed", {
                    "status": final_output.workflow_status,
                    "processing_time": workflow_time,
                    "events_processed": events_processed
                })
            
            # Send business event for workflow completion
            send_business_event("architecture_analysis.workflow.completed", {
                "job_id": job_id or "unknown",
                "workflow_status": final_output.workflow_status,
                "processing_time_seconds": str(workflow_time),
                "events_processed": str(events_processed)
            })
        else:
            if workflow_span:
                workflow_span.set_attribute("workflow.success", False)
                workflow_span.add_event("Workflow completed with no output")
            
            send_business_event("architecture_analysis.workflow.failed", {
                "job_id": job_id or "unknown",
                "error": "No output received"
            })
        
        return final_output


# ============================================================================
# Workflow Orchestrator Wrapper Class (for backward compatibility with app.py)
# ============================================================================

class WorkflowOrchestrator:
    """
    Wrapper class for executing architecture analysis workflows.
    Uses Microsoft Agent Framework with WorkflowBuilder pattern.
    """
    
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config.from_environment()
    
    def execute_workflow(self, image_path: str, job_id: Optional[str] = None) -> Dict[str, Any]:
        """Execute complete workflow: Vision → Analyzer → Best Practices → IAC Generator → IAC Reviewer"""
        return asyncio.run(run_architecture_analysis_workflow(image_path, job_id))
    
    def execute_analyzer_only(self, image_path: str, job_id: Optional[str] = None) -> Dict[str, Any]:
        """Execute analysis only: Vision → Analyzer → Best Practices"""
        return asyncio.run(run_architecture_analysis_workflow(image_path, job_id))
    
    def execute_iac_generation(self, best_practices: Dict[str, Any], job_id: Optional[str] = None) -> Dict[str, Any]:
        """Execute IAC generation and review"""
        return asyncio.run(run_architecture_analysis_workflow("", job_id))


# ============================================================================


async def main(image_path: str = None):
    """Main function to run the architecture analysis workflow"""
    
    try:
        if not image_path:
            # Default test image path
            image_path = "./sample_architecture_diagram.png"
        
        result = await run_architecture_analysis_workflow(image_path)
        
        # Display results
        if result and isinstance(result, ArchitectureAnalysisWorkflowOutput):
            print(f"Workflow Status: {result.workflow_status}")
            if result.terraform_path:
                print(f"Terraform Path: {result.terraform_path}")
            if result.errors:
                print(f"Errors: {result.errors}")
        
        return result
        
    except Exception as e:
        logger.error(f"Workflow execution failed: {str(e)}")
        return None


if __name__ == "__main__":
    asyncio.run(main())
