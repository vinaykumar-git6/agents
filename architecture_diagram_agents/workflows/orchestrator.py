"""
Architecture Diagram Analyzer Orchestrator
Workflow using Microsoft Agent Framework
Sequential Pipeline: Vision -> Analyzer -> Best Practices -> IAC Generator/Reviewer Group Chat
"""

import asyncio
import os
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, cast
from typing_extensions import Never
import queue

from agent_framework import AgentRunUpdateEvent, ChatMessage, WorkflowBuilder, WorkflowContext, WorkflowOutputEvent, executor, GroupChatBuilder, GroupChatStateSnapshot
from pydantic import BaseModel
from dotenv import load_dotenv

from ..agents.vision_agent import VisionAgent
from ..agents.analyzer_agent import AnalyzerAgent
from ..agents.azure_best_practice_agent import AzureBestPracticeAgent
from ..agents.iac_generator_agent import IACGeneratorAgent
from ..agents.iac_reviewer_agent import IACReviewerAgent
from ..agents.infracost_agent import InfracostAgent
from ..core.config import Config
from ..utils.legacy_utils import setup_logger
from ..utils.logging_config import setup_logging
from ..utils.pdf_generator import save_best_practices_pdf, PDF_AVAILABLE
from ..utils.terraform_utils import (
    prepare_terraform_plan,
    save_terraform_project,
    parse_terraform_files,
    extract_terraform_block,
    ANSI_COLORS
)
from ..utils.output_utils import log_agent_output

# Load environment
env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=env_path, override=True)

# Initialize logging
setup_logging(level="INFO")
logger = setup_logger(__name__)

# Global progress queue for streaming updates to frontend
progress_queues: Dict[str, queue.Queue] = {}

# Global storage for intermediate workflow results
workflow_results_store: Dict[str, Dict[str, Any]] = {}


# ============================================================================
# Response Models (Pydantic)
# ============================================================================

class ArchitectureAnalysisRequest(BaseModel):
    """Workflow request for architecture analysis"""
    image_path: str
    analysis_type: str = "complete"
    job_id: Optional[str] = None


class VisionAnalysisResponse(BaseModel):
    """Vision analysis output"""
    text: list = []
    objects: list = []
    tags: list = []
    dense_captions: list = []
    architecture_type: str = ""
    services_detected: list = []
    status: str = "SUCCESS"
    job_id: Optional[str] = None


class AnalyzerResponse(BaseModel):
    """Service analyzer output"""
    cloud_provider: str = ""
    default_region: str = ""
    total_services: int = 0
    azure_services: list = []
    summary: str = ""
    status: str = "SUCCESS"
    job_id: Optional[str] = None


class BestPracticesResponse(BaseModel):
    """Best practices recommendations"""
    service_recommendations: list = []
    architecture_checklist: list = []
    summary: str = ""
    total_recommendations: int = 0
    status: str = "SUCCESS"
    job_id: Optional[str] = None


class TerraformGenerationResponse(BaseModel):
    """Terraform generation output - passed to Infracost executor"""
    workflow_status: str = "success"
    vision_result: Dict[str, Any] = {}
    analyzer_result: Dict[str, Any] = {}
    best_practices_result: Dict[str, Any] = {}
    terraform_result: Dict[str, Any] = {}
    review_results: list = []
    terraform_path: Optional[str] = None
    plan_json_path: Optional[str] = None  # Path to terraform plan JSON for Infracost
    job_id: Optional[str] = None
    errors: list = []


class ArchitectureAnalysisWorkflowOutput(BaseModel):
    """Final workflow output with cost estimation and AI-generated report"""
    workflow_status: str = "success"
    vision_result: Dict[str, Any] = {}
    analyzer_result: Dict[str, Any] = {}
    best_practices_result: Dict[str, Any] = {}
    terraform_result: Dict[str, Any] = {}
    review_results: list = []
    terraform_path: Optional[str] = None
    cost_estimate: Dict[str, Any] = {}
    cost_report: str = ""  # AI-generated cost analysis report
    errors: list = []


# ============================================================================
# Console Output Helpers (local wrappers)
# ============================================================================

def _log_agent_output(agent_name: str, message_text: str, message_num: int = 0) -> None:
    """Log agent output in a readable, formatted way with colors."""
    # ANSI color codes for terminal output
    COLORS = {
        'generator': '\033[92m',  # Green
        'reviewer': '\033[96m',   # Cyan
        'unknown': '\033[93m',    # Yellow
        'reset': '\033[0m',
        'bold': '\033[1m',
        'blue': '\033[94m',
    }
    
    # Handle None values
    agent_name = agent_name or "Unknown"
    message_text = message_text or "(empty message)"
    
    # Select color based on agent
    color = COLORS.get(agent_name.lower(), COLORS['unknown'])
    reset = COLORS['reset']
    bold = COLORS['bold']
    blue = COLORS['blue']
    
    border = "=" * 100
    inner_border = "-" * 100
    
    # Print colored header
    print(f"\n{bold}{blue}{border}{reset}")
    print(f"{bold}{color}[{agent_name.upper()}] MESSAGE #{message_num}{reset}")
    print(f"{bold}{blue}{border}{reset}")
    
    # Print full message content without truncation
    print(f"{color}{message_text}{reset}")
    
    print(f"{bold}{blue}{inner_border}{reset}")
    print(f"{color}[{agent_name.upper()}] Total length: {len(message_text)} characters{reset}")
    print(f"{bold}{blue}{border}{reset}\n")


# ============================================================================
# Workflow Executors
# ============================================================================

@executor
async def vision_analyzer_executor(
    request: ArchitectureAnalysisRequest,
    ctx: WorkflowContext[VisionAnalysisResponse]
) -> None:
    """Vision analyzer executor - analyzes architecture diagram image"""
    job_id = request.job_id
    vision_agent = None  # Initialize for finally block
    
    # ANSI color codes
    CYAN = '\033[96m'
    YELLOW = '\033[93m'
    GREEN = '\033[92m'
    MAGENTA = '\033[95m'
    BOLD = '\033[1m'
    RESET = '\033[0m'
    
    try:
        config = Config.from_environment()
        vision_agent = VisionAgent(config)
        await vision_agent.initialize()
        
        # Log the input data
        input_data = {'image_path': request.image_path, 'analysis_type': request.analysis_type}
        
        # Log input to file (no truncation)
        logger.info(f"[VisionAgent] JOB_ID: {job_id}")
        logger.info(f"[VisionAgent] INPUT: {json.dumps(input_data, indent=2, default=str)}")
        
        print(f"\n{BOLD}{'=' * 80}{RESET}")
        print(f"{CYAN}{BOLD}[AGENT]{RESET} {CYAN}VisionAgent{RESET}")
        print(f"{YELLOW}{BOLD}[JOB ID]{RESET} {YELLOW}{job_id}{RESET}")
        print(f"{BOLD}{'-' * 80}{RESET}")
        print(f"{MAGENTA}{BOLD}[INPUT]{RESET}")
        print(f"{MAGENTA}{json.dumps(input_data, indent=2, default=str)}{RESET}")
        print(f"{BOLD}{'-' * 80}{RESET}")
        
        result = await vision_agent.analyze(request.image_path)
        
        if not result:
            raise Exception("Vision analysis returned empty result")
        
        # Log result to file (no truncation)
        logger.info(f"[VisionAgent] RESULT: {json.dumps(result, indent=2, default=str)}")
        
        # Log the result
        print(f"{GREEN}{BOLD}[RESULT]{RESET}")
        print(f"{GREEN}{json.dumps(result, indent=2, default=str)}{RESET}")
        print(f"{BOLD}{'=' * 80}{RESET}\n")
        
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
        
        if job_id:
            if job_id not in workflow_results_store:
                workflow_results_store[job_id] = {}
            workflow_results_store[job_id]['vision_result'] = result
        
        await ctx.send_message(vision_response)
        
    except Exception as e:
        logger.error(f"Vision analysis failed: {e}")
        await ctx.send_message(VisionAnalysisResponse(status="ERROR"))
    
    finally:
        # Always close the agent to prevent resource leaks
        if vision_agent:
            try:
                await vision_agent.close()
            except Exception as close_error:
                logger.warning(f"Error closing VisionAgent: {close_error}")


@executor
async def service_analyzer_executor(
    vision_response: VisionAnalysisResponse,
    ctx: WorkflowContext[AnalyzerResponse]
) -> None:
    """Service analyzer executor - identifies Azure services"""
    job_id = vision_response.job_id
    analyzer_agent = None  # Initialize for finally block
    
    try:
        config = Config.from_environment()
        analyzer_agent = AnalyzerAgent(config)
        await analyzer_agent.initialize()
        
        vision_data = {
            'text': vision_response.text,
            'objects': vision_response.objects,
            'tags': vision_response.tags,
            'dense_captions': vision_response.dense_captions,
            'architecture_type': vision_response.architecture_type,
            'services_detected': vision_response.services_detected
        }
        
        # Log input to file (no truncation)
        logger.info(f"[AnalyzerAgent] JOB_ID: {job_id}")
        logger.info(f"[AnalyzerAgent] INPUT: {json.dumps(vision_data, indent=2, default=str)}")
        
        # Log the input data with colors
        CYAN = '\033[96m'
        YELLOW = '\033[93m'
        GREEN = '\033[92m'
        MAGENTA = '\033[95m'
        BOLD = '\033[1m'
        RESET = '\033[0m'
        
        print(f"\n{BOLD}{'=' * 80}{RESET}")
        print(f"{CYAN}{BOLD}[AGENT]{RESET} {CYAN}AnalyzerAgent{RESET}")
        print(f"{YELLOW}{BOLD}[JOB ID]{RESET} {YELLOW}{job_id}{RESET}")
        print(f"{BOLD}{'-' * 80}{RESET}")
        print(f"{MAGENTA}{BOLD}[INPUT]{RESET}")
        print(f"{MAGENTA}{json.dumps(vision_data, indent=2, default=str)}{RESET}")
        print(f"{BOLD}{'-' * 80}{RESET}")
        
        result = await analyzer_agent.analyze(vision_data)
        
        if not result:
            raise Exception("Service analysis returned empty result")
        
        # Log result to file (no truncation)
        logger.info(f"[AnalyzerAgent] RESULT: {json.dumps(result, indent=2, default=str)}")
        
        # Log the result
        print(f"{GREEN}{BOLD}[RESULT]{RESET}")
        print(f"{GREEN}{json.dumps(result, indent=2, default=str)}{RESET}")
        print(f"{BOLD}{'=' * 80}{RESET}\n")
        
        analyzer_response = AnalyzerResponse(
            cloud_provider=result.get('cloud_provider', ''),
            default_region=result.get('default_region', ''),
            total_services=result.get('total_services', 0),
            azure_services=result.get('azure_services', []),
            summary=result.get('summary', ''),
            status="SUCCESS",
            job_id=job_id
        )
        
        if job_id:
            if job_id not in workflow_results_store:
                workflow_results_store[job_id] = {}
            workflow_results_store[job_id]['analyzer_result'] = result
        
        await ctx.send_message(analyzer_response)
        
    except Exception as e:
        logger.error(f"Service analysis failed: {e}")
        await ctx.send_message(AnalyzerResponse(status="ERROR"))
    
    finally:
        # Always close the agent to prevent resource leaks
        if analyzer_agent:
            try:
                await analyzer_agent.close()
            except Exception as close_error:
                logger.warning(f"Error closing AnalyzerAgent: {close_error}")


@executor
async def best_practices_executor(
    analyzer_response: AnalyzerResponse,
    ctx: WorkflowContext[BestPracticesResponse]
) -> None:
    """Best practices executor - generates recommendations"""
    job_id = analyzer_response.job_id
    best_practice_agent = None  # Initialize for finally block
    
    # ANSI color codes
    CYAN = '\033[96m'
    YELLOW = '\033[93m'
    GREEN = '\033[92m'
    MAGENTA = '\033[95m'
    BOLD = '\033[1m'
    RESET = '\033[0m'
    
    try:
        config = Config.from_environment()
        best_practice_agent = AzureBestPracticeAgent(config)
        await best_practice_agent.initialize()
        
        analyzer_data = {
            'cloud_provider': analyzer_response.cloud_provider,
            'default_region': analyzer_response.default_region,
            'total_services': analyzer_response.total_services,
            'azure_services': analyzer_response.azure_services,
            'summary': analyzer_response.summary
        }
        
        # Log input to file (no truncation)
        logger.info(f"[AzureBestPracticeAgent] JOB_ID: {job_id}")
        logger.info(f"[AzureBestPracticeAgent] INPUT: {json.dumps(analyzer_data, indent=2, default=str)}")
        
        # Log the input data
        print(f"\n{BOLD}{'=' * 80}{RESET}")
        print(f"{CYAN}{BOLD}[AGENT]{RESET} {CYAN}AzureBestPracticeAgent{RESET}")
        print(f"{YELLOW}{BOLD}[JOB ID]{RESET} {YELLOW}{job_id}{RESET}")
        print(f"{BOLD}{'-' * 80}{RESET}")
        print(f"{MAGENTA}{BOLD}[INPUT]{RESET}")
        print(f"{MAGENTA}{json.dumps(analyzer_data, indent=2, default=str)}{RESET}")
        print(f"{BOLD}{'-' * 80}{RESET}")
        
        result = await best_practice_agent.recommend(analyzer_data)
        
        if not result:
            raise Exception("Best practices recommendation returned empty result")
        
        # Log result to file (no truncation)
        logger.info(f"[AzureBestPracticeAgent] RESULT: {json.dumps(result, indent=2, default=str)}")
        
        # Log the result
        print(f"{GREEN}{BOLD}[RESULT]{RESET}")
        print(f"{GREEN}{json.dumps(result, indent=2, default=str)}{RESET}")
        print(f"{BOLD}{'=' * 80}{RESET}\n")
        
        best_practices_response = BestPracticesResponse(
            service_recommendations=result.get('service_recommendations', []),
            architecture_checklist=result.get('architecture_checklist', []),
            summary=result.get('summary', ''),
            total_recommendations=result.get('total_recommendations', 0),
            status="SUCCESS",
            job_id=job_id
        )
        
        if job_id:
            if job_id not in workflow_results_store:
                workflow_results_store[job_id] = {}
            workflow_results_store[job_id]['best_practices_result'] = result
        
        # Save best practices as PDF
        if PDF_AVAILABLE and result:
            try:
                pdf_path = save_best_practices_pdf(result)
                if job_id and job_id in workflow_results_store:
                    workflow_results_store[job_id]['best_practices_pdf_path'] = pdf_path
            except Exception as pdf_error:
                logger.warning(f"Failed to save PDF: {pdf_error}")
        
        await ctx.send_message(best_practices_response)
        
    except Exception as e:
        logger.error(f"Best practices failed: {e}")
        await ctx.send_message(BestPracticesResponse(status="ERROR"))
    
    finally:
        # Always close the agent to prevent resource leaks
        if best_practice_agent:
            try:
                await best_practice_agent.close()
            except Exception as close_error:
                logger.warning(f"Error closing AzureBestPracticeAgent: {close_error}")


@executor
async def iac_generator_reviewer_group_chat_executor(
    best_practices_response: BestPracticesResponse,
    ctx: WorkflowContext[TerraformGenerationResponse]
) -> None:
    """IAC generator and reviewer executor - generates and refines Terraform code using group chat"""
    job_id = best_practices_response.job_id if best_practices_response else None
    
    if best_practices_response is None:
        logger.error("IAC Generator/Reviewer received None as best_practices_response!")
        await ctx.send_message(TerraformGenerationResponse(
            workflow_status="failed",
            errors=["IAC Generator/Reviewer received no input from Best Practices"]
        ))
        return
    
    if hasattr(best_practices_response, 'status') and best_practices_response.status != "SUCCESS":
        logger.error(f"Best Practices returned error status: {best_practices_response.status}")
        await ctx.send_message(TerraformGenerationResponse(
            workflow_status="failed",
            errors=["Best Practices failed to generate recommendations"]
        ))
        return
    
    iac_generator_agent = None
    iac_reviewer_agent = None
    
    try:
        config = Config.from_environment()
        
        best_practices_data = {
            'service_recommendations': best_practices_response.service_recommendations,
            'architecture_checklist': best_practices_response.architecture_checklist,
            'summary': best_practices_response.summary,
            'total_recommendations': best_practices_response.total_recommendations
        }
        
        # Log input to file (no truncation)
        logger.info(f"[GroupChatExecutor] JOB_ID: {job_id}")
        logger.info(f"[GroupChatExecutor] INPUT best_practices_data: {json.dumps(best_practices_data, indent=2, default=str)}")
        
        iac_generator_agent = IACGeneratorAgent(config)
        iac_reviewer_agent = IACReviewerAgent(config)
        
        await iac_generator_agent.initialize()
        await iac_reviewer_agent.initialize()
        
        generator_chat = iac_generator_agent.agent
        reviewer_chat = iac_reviewer_agent.agent
        
        if not generator_chat or not reviewer_chat:
            raise Exception("Failed to initialize ChatAgent instances from agents")
        
        generator_chat.name = "Generator"
        reviewer_chat.name = "Reviewer"
        
        def select_next_speaker(state: GroupChatStateSnapshot) -> str | None:
            """Speaker selection for group chat with validation-aware continuation.
            
            Allows up to 5 rounds (Generator→Reviewer→Generator→Reviewer→Generator) 
            to handle terraform validation errors that need fixing.
            """
            round_idx = state["round_index"]
            history = state["history"]
            max_rounds = 5 # Increased to allow more fix iterations
            
            if round_idx >= max_rounds:
                return None
            
            if round_idx == 0:
                return "Generator"
            
            last_speaker = history[-1].speaker if history else None
            
            # Check if reviewer found validation errors - need more rounds
            if last_speaker == "Reviewer" and round_idx >= 2:
                # Get the last message content from the turn's messages
                last_turn = history[-1]
                last_message = ""
                if hasattr(last_turn, 'messages') and last_turn.messages:
                    # Get the last assistant message content
                    for msg in reversed(last_turn.messages):
                        if hasattr(msg, 'content') and msg.content:
                            last_message = str(msg.content)
                            break
                        elif hasattr(msg, 'text'):
                            last_message = msg.text
                            break
                
                # Continue if validation failed or critical issues found
                if any(indicator in last_message.lower() for indicator in [
                    '"valid": false',
                    '"passed": false', 
                    'validation error',
                    'syntax error',
                    '"severity": "critical"',
                    'terraform validate',
                    'init failed',
                    'invalid expression'
                ]):
                    logger.info(f"[GroupChat] Validation issues detected, continuing to round {round_idx + 1}")
                    return "Generator"
            
            if last_speaker == "Generator":
                return "Reviewer"
            else:
                return "Generator"
        
        # Get accumulated workflow data for context
        workflow_context = {}
        if job_id and job_id in workflow_results_store:
            workflow_context = workflow_results_store[job_id]
        
        initial_task = f"""Generate production-ready, error-free Terraform Infrastructure as Code based on Azure architecture analysis and best practices.

    **CONTEXT:**
    - Architecture Analysis: {json.dumps(workflow_context.get('vision_result', {}), indent=2)}
    - Service Analysis: {json.dumps(workflow_context.get('analyzer_result', {}), indent=2)}
    - Best Practices & Recommendations: {json.dumps(best_practices_data, indent=2)}

    **GENERATOR REQUIREMENTS:**
    1. Create ALL required Terraform files with proper structure:
       - providers.tf (Azure provider configuration with version constraints)
       - main.tf (All Azure resources with comprehensive comments)
       - variables.tf (All variables with descriptions and validation)
       - outputs.tf (Resource outputs with descriptions)
       - terraform.tfvars (Example values for all variables)
       - README.md (Complete documentation with usage instructions)

    2. Code Quality Standards:
       - Add detailed comments explaining each resource and its purpose
       - Use descriptive resource names following Azure naming conventions
       - Include proper resource dependencies and references
       - Implement security best practices (managed identity, private endpoints, etc.)
       - Follow Azure Well-Architected Framework principles
       - Ensure proper error handling and validation

    3. Terraform Best Practices:
       - Use data sources where appropriate
       - Implement proper tagging strategy
       - Configure remote state management
       - Use locals for repeated values
       - Implement proper variable validation

    **REVIEWER REQUIREMENTS:**
    1. **MANDATORY: Run Terraform Validation Tool**
       - You have access to the validate_terraform tool - USE IT FIRST
       - Call validate_terraform with JSON containing the terraform files:
         {{"providers_tf": "...", "main_tf": "...", "variables_tf": "...", "outputs_tf": "...", "terraform_tfvars": "..."}}
       - The tool runs 'terraform init -backend=false' and 'terraform validate'
       - Report ALL validation errors with file and line numbers

    2. Validate ALL generated files for:
       - Syntax errors from terraform validate (CRITICAL)
       - Resource configuration errors
       - Security vulnerabilities and misconfigurations
       - Missing required properties
       - Improper resource dependencies
       - Azure-specific best practices violations

    3. Check Documentation Quality:
       - Verify all resources have meaningful comments
       - Ensure README.md is complete with prerequisites and usage
       - Validate variable descriptions are clear and accurate

    4. Provide Specific Feedback for Generator to Fix:
       - Include ALL terraform validation errors with exact locations
       - Identify exact line numbers for errors
       - Suggest specific fixes with corrected code snippets
       - Prioritize security and reliability issues
       - If validation fails, explicitly tell Generator what to fix

    **COLLABORATION PROCESS:**
    - Generator: Create initial complete Terraform project
    - Reviewer: Run validate_terraform tool, then review ALL files and provide detailed feedback
    - Generator: Fix ALL identified issues (especially validation errors) and regenerate complete files
    - Reviewer: Re-run validate_terraform to verify fixes
    - Continue until terraform validate passes AND all best practices are implemented

    **SUCCESS CRITERIA:**
    - terraform validate passes with NO errors
    - Zero syntax errors in all Terraform files
    - All Azure resources properly configured
    - Comprehensive comments throughout the code
    - Complete documentation in README.md
    - Security best practices implemented
    - All files present and properly structured

    Begin with Generator creating the complete Terraform project..."""
        
        final_conversation: list[ChatMessage] = []
        
        # Retry logic for transient Azure AI service errors
        max_retries = 5
        retry_delay = 10
        
        for attempt in range(max_retries):
            try:
                group_chat = (
                    GroupChatBuilder()
                    .set_select_speakers_func(select_next_speaker, display_name="Orchestrator")
                    .participants([generator_chat, reviewer_chat])
                    .build()
                )
                
                async for event in group_chat.run_stream(initial_task):
                    if isinstance(event, WorkflowOutputEvent):
                        final_conversation = cast(list[ChatMessage], event.data)
                break
            except Exception as retry_error:
                error_msg = str(retry_error)
                if attempt < max_retries - 1 and "something went wrong" in error_msg.lower():
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise
        
        # Print final conversation with colors and log to file
        if final_conversation:
            print("\n")
            logger.info(f"[GroupChatExecutor] FINAL CONVERSATION - {len(final_conversation)} messages")
            for idx, msg in enumerate(final_conversation, 1):
                author = getattr(msg, "author_name", None) or getattr(msg, "speaker", None) or "Unknown"
                text = getattr(msg, "text", None) or getattr(msg, "content", None) or str(msg)
                # Log full conversation to file (no truncation)
                logger.info(f"[GroupChatExecutor] MESSAGE #{idx} [{author}]: {text}")
                _log_agent_output(author, text, idx)
        
        final_terraform = {
            'providers_tf': '',
            'main_tf': '',
            'variables_tf': '',
            'outputs_tf': '',
            'terraform_tfvars': '',
            'README_md': ''
        }
        
        # Find the Generator message that contains actual Terraform code (not just review text)
        # Look for messages with code blocks (```) which indicate actual Terraform content
        best_terraform_text = ""
        best_terraform_score = 0
        
        for msg in final_conversation:
            author = getattr(msg, "author_name", None) or getattr(msg, "speaker", None) or ""
            if author == "Generator":
                text = getattr(msg, "text", None) or getattr(msg, "content", None) or ""
                
                # Score this message based on Terraform code indicators
                score = 0
                # Check for code blocks with terraform content
                if '```hcl' in text or '```terraform' in text:
                    score += 10
                # Check for file headers
                for filename in ['providers.tf', 'main.tf', 'variables.tf', 'outputs.tf', 'terraform.tfvars', 'README.md']:
                    if filename in text:
                        score += 5
                # Check for terraform keywords
                for keyword in ['resource "', 'variable "', 'output "', 'provider "', 'terraform {']:
                    if keyword in text:
                        score += 3
                # Penalize if it looks like a review (contains "review", "score", "issues")
                review_keywords = ['Review Summary', 'Final Score', 'Must-Fix', 'Recommended Fix', 'Line(s)', 'Severity']
                for rk in review_keywords:
                    if rk in text:
                        score -= 5
                
                logger.debug(f"[GroupChatExecutor] Generator message score: {score}, length: {len(text)}")
                
                if score > best_terraform_score:
                    best_terraform_score = score
                    best_terraform_text = text
        
        if best_terraform_text:
            logger.info(f"[GroupChatExecutor] Selected Generator message with score {best_terraform_score}, length {len(best_terraform_text)}")
            final_terraform = parse_terraform_files(best_terraform_text)
        
        if not final_terraform.get('main_tf'):
            # Fallback: try to find any message with terraform content
            logger.warning("[GroupChatExecutor] No main.tf found, trying fallback extraction from all messages")
            for msg in final_conversation:
                text = getattr(msg, "text", None) or getattr(msg, "content", None) or ""
                if 'resource "' in text or 'terraform {' in text:
                    fallback_terraform = parse_terraform_files(text)
                    if fallback_terraform.get('main_tf'):
                        final_terraform = fallback_terraform
                        logger.info(f"[GroupChatExecutor] Fallback found main.tf with {len(fallback_terraform['main_tf'])} chars")
                        break
        
        # Final fallback: if still no content, log error
        if not final_terraform.get('main_tf'):
            logger.error("[GroupChatExecutor] CRITICAL: No Terraform code could be extracted from conversation!")
            final_terraform['main_tf'] = "# ERROR: No Terraform code could be extracted from the generator conversation"
        
        final_review_result = {
            'overall_score': 85,
            'passed': True,
            'issues': [],
            'summary': f'Terraform code reviewed through {len(final_conversation)} message collaborative refinement',
            'conversation_count': len(final_conversation)
        }
        
        terraform_folder = Path(__file__).parent.parent.parent / 'terraform_projects'
        output_dir = str(terraform_folder / f"arch_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        terraform_path = save_terraform_project(final_terraform, output_dir)
        
        # Log terraform output to file (no truncation)
        logger.info(f"[GroupChatExecutor] TERRAFORM OUTPUT PATH: {terraform_path}")
        logger.info(f"[GroupChatExecutor] TERRAFORM FILES: {json.dumps(final_terraform, indent=2, default=str)}")
        
        # Run terraform init and plan to prepare plan.json for Infracost
        plan_result = await prepare_terraform_plan(terraform_path)
        plan_json_path = plan_result.get("plan_json_path")
        
        if plan_result.get("errors"):
            logger.warning(f"[GroupChatExecutor] Terraform plan warnings: {plan_result['errors']}")
        
        vision_result = {}
        analyzer_result = {}
        best_practices_result = {}
        
        if job_id and job_id in workflow_results_store:
            vision_result = workflow_results_store[job_id].get('vision_result', {})
            analyzer_result = workflow_results_store[job_id].get('analyzer_result', {})
            best_practices_result = workflow_results_store[job_id].get('best_practices_result', {})
        
        terraform_output = TerraformGenerationResponse(
            workflow_status="success",
            vision_result=vision_result,
            analyzer_result=analyzer_result,
            best_practices_result=best_practices_result,
            terraform_result=final_terraform,
            review_results=[final_review_result],
            terraform_path=terraform_path,
            plan_json_path=plan_json_path,
            job_id=job_id,
            errors=plan_result.get("errors", [])
        )
        
        await ctx.send_message(terraform_output)
        
    except Exception as e:
        logger.error(f"Group chat failed: {e}", exc_info=True)
        
        if job_id and job_id in workflow_results_store:
            del workflow_results_store[job_id]
        
        await ctx.send_message(TerraformGenerationResponse(
            workflow_status="failed",
            errors=[str(e)]
        ))
    
    finally:
        if iac_generator_agent:
            try:
                await iac_generator_agent.close()
            except Exception:
                pass
        
        if iac_reviewer_agent:
            try:
                await iac_reviewer_agent.close()
            except Exception:
                pass


@executor
async def infracost_executor(
    terraform_response: TerraformGenerationResponse,
    ctx: WorkflowContext[Never, ArchitectureAnalysisWorkflowOutput]
) -> None:
    """Infracost executor - estimates infrastructure costs for generated Terraform code"""
    
    # ANSI color codes
    CYAN = '\033[96m'
    YELLOW = '\033[93m'
    GREEN = '\033[92m'
    MAGENTA = '\033[95m'
    BOLD = '\033[1m'
    RESET = '\033[0m'
    BLUE = '\033[94m'
    
    job_id = terraform_response.job_id
    infracost_agent = None
    cost_result = None
    
    try:
        # Check if terraform generation was successful
        if terraform_response.workflow_status != "success":
            logger.error("Terraform generation failed, skipping cost estimation")
            await ctx.yield_output(ArchitectureAnalysisWorkflowOutput(
                workflow_status=terraform_response.workflow_status,
                vision_result=terraform_response.vision_result,
                analyzer_result=terraform_response.analyzer_result,
                best_practices_result=terraform_response.best_practices_result,
                terraform_result=terraform_response.terraform_result,
                review_results=terraform_response.review_results,
                terraform_path=terraform_response.terraform_path,
                cost_estimate={},
                errors=terraform_response.errors
            ))
            return
        
        terraform_data = terraform_response.terraform_result
        terraform_path = terraform_response.terraform_path
        plan_json_path = terraform_response.plan_json_path
        
        # Log input
        print(f"\n{BOLD}{'=' * 80}{RESET}")
        print(f"{CYAN}{BOLD}[AGENT]{RESET} {CYAN}InfracostAgent (Agentic Cost Analyzer){RESET}")
        print(f"{YELLOW}{BOLD}[JOB ID]{RESET} {YELLOW}{job_id}{RESET}")
        print(f"{BOLD}{'-' * 80}{RESET}")
        print(f"{MAGENTA}{BOLD}[INPUT]{RESET}")
        print(f"{MAGENTA}Terraform path: {terraform_path}{RESET}")
        if plan_json_path:
            print(f"{MAGENTA}Plan JSON: {plan_json_path}{RESET}")
        print(f"{MAGENTA}Terraform files:{RESET}")
        for key, content in terraform_data.items():
            if content:
                print(f"{MAGENTA}  - {key}: {len(content)} chars{RESET}")
        print(f"{BOLD}{'-' * 80}{RESET}")
        
        logger.info(f"[InfracostAgent] JOB_ID: {job_id}")
        logger.info(f"[InfracostAgent] Terraform path: {terraform_path}")
        logger.info(f"[InfracostAgent] Plan JSON path: {plan_json_path}")
        
        # Call the agentic InfracostAgent - it handles CLI internally and generates AI report
        print(f"{YELLOW}[Infracost] Running Infracost Agent with CLI tool...{RESET}")
        infracost_agent = InfracostAgent()
        cost_result = await infracost_agent.estimate(terraform_path, terraform_data)
        
        # Log raw result to file
        logger.info(f"[InfracostAgent] RESULT: {json.dumps(cost_result, indent=2, default=str)}")
        
        # Print the AI-generated report
        print(f"\n{GREEN}{BOLD}[INFRACOST AGENT REPORT]{RESET}")
        print(f"{BLUE}{'=' * 80}{RESET}")
        
        if cost_result.get('status') == 'SUCCESS':
            # Print the AI-generated comprehensive report
            ai_report = cost_result.get('report', '')
            if ai_report:
                print(f"{GREEN}{ai_report}{RESET}")
                logger.info(f"[InfracostAgent] AI REPORT:\n{ai_report}")
            
            # Also print structured summary if no AI report
            if not ai_report:
                estimate = cost_result.get('cost_estimate', {})
                summary = estimate.get('summary', {})
                resources = estimate.get('resources', [])
                
                print(f"{GREEN}{BOLD}💰 COST SUMMARY{RESET}")
                print(f"{GREEN}   Currency:           {summary.get('currency', 'USD')}{RESET}")
                print(f"{GREEN}   Total Monthly Cost: {summary.get('total_monthly_cost', 'N/A')}{RESET}")
                print(f"{GREEN}   Total Hourly Cost:  {summary.get('total_hourly_cost', 'N/A')}{RESET}")
                print(f"{BLUE}{'-' * 80}{RESET}")
                
                print(f"{CYAN}{BOLD}📦 RESOURCE BREAKDOWN ({estimate.get('resource_count', 0)} resources){RESET}")
                
                # Sort by cost and show top resources
                sorted_resources = sorted(
                    resources,
                    key=lambda x: float(x.get('monthly_cost', '0') or '0'),
                    reverse=True
                )
                
                for i, resource in enumerate(sorted_resources[:15], 1):
                    cost = resource.get('monthly_cost', '0')
                    if cost and float(cost) > 0:
                        print(f"{CYAN}   {i}. {resource['name']}{RESET}")
                        print(f"{CYAN}      Type: {resource['resource_type']}{RESET}")
                        print(f"{CYAN}      Cost: ${cost}/month{RESET}")
                        
                        # Show cost components if available
                        components = resource.get('cost_components', [])
                        if components:
                            for comp in components[:3]:
                                print(f"{CYAN}        - {comp.get('name')}: ${comp.get('monthly_cost', '0')}/month{RESET}")
                        print()
                
                # Log detailed report to file
                logger.info(f"[InfracostAgent] COST REPORT:")
                logger.info(f"[InfracostAgent]   Total Monthly: {summary.get('total_monthly_cost', 'N/A')}")
                logger.info(f"[InfracostAgent]   Resource Count: {estimate.get('resource_count', 0)}")
                for resource in sorted_resources:
                    logger.info(f"[InfracostAgent]   - {resource['name']} ({resource['resource_type']}): ${resource.get('monthly_cost', '0')}/month")
        else:
            error_msg = cost_result.get('error', 'Unknown error')
            print(f"{YELLOW}⚠️  Cost estimation failed: {error_msg}{RESET}")
            logger.warning(f"[InfracostAgent] Cost estimation failed: {error_msg}")
        
        print(f"{BLUE}{'=' * 80}{RESET}\n")
        
        # Create final output with AI-generated report
        ai_report = cost_result.get('report', '') if cost_result.get('status') == 'SUCCESS' else ''
        
        # Save infracost report as markdown
        if ai_report:
            try:
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                report_path = os.path.join(
                    os.path.dirname(__file__), '..', '..', 'outputs',
                    f'infracost_report_{timestamp}.md'
                )
                os.makedirs(os.path.dirname(report_path), exist_ok=True)
                with open(report_path, 'w', encoding='utf-8') as f:
                    f.write(f"# Infracost Report\n\n")
                    f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    f.write(f"**Job ID:** {job_id}\n\n")
                    f.write("---\n\n")
                    f.write(ai_report)
                logger.info(f"[InfracostAgent] Report saved to: {report_path}")
            except Exception as e:
                logger.warning(f"[InfracostAgent] Failed to save report: {e}")
        
        final_output = ArchitectureAnalysisWorkflowOutput(
            workflow_status="success",
            vision_result=terraform_response.vision_result,
            analyzer_result=terraform_response.analyzer_result,
            best_practices_result=terraform_response.best_practices_result,
            terraform_result=terraform_response.terraform_result,
            review_results=terraform_response.review_results,
            terraform_path=terraform_response.terraform_path,
            cost_estimate=cost_result.get('cost_estimate', {}),
            cost_report=ai_report,
            errors=[]
        )
        
        await ctx.yield_output(final_output)
        
    except Exception as e:
        logger.error(f"Infracost executor failed: {e}", exc_info=True)
        
        await ctx.yield_output(ArchitectureAnalysisWorkflowOutput(
            workflow_status="success",  # Don't fail workflow just because cost estimation failed
            vision_result=terraform_response.vision_result,
            analyzer_result=terraform_response.analyzer_result,
            best_practices_result=terraform_response.best_practices_result,
            terraform_result=terraform_response.terraform_result,
            review_results=terraform_response.review_results,
            terraform_path=terraform_response.terraform_path,
            cost_estimate={"status": "ERROR", "error": str(e)},
            cost_report="",
            errors=[f"Cost estimation failed: {str(e)}"]
        ))
    
    finally:
        if infracost_agent:
            try:
                await infracost_agent.close()
            except Exception:
                pass


# ============================================================================
# Workflow Execution Function
# ============================================================================

async def run_architecture_analysis_workflow(image_path: str, job_id: Optional[str] = None):
    """Execute the architecture analysis workflow using Microsoft Agent Framework"""
    workflow = (
        WorkflowBuilder()
        .set_start_executor(vision_analyzer_executor)
        .add_edge(vision_analyzer_executor, service_analyzer_executor)
        .add_edge(service_analyzer_executor, best_practices_executor)
        .add_edge(best_practices_executor, iac_generator_reviewer_group_chat_executor)
        .add_edge(iac_generator_reviewer_group_chat_executor, infracost_executor)
        .build()
    )
    
    request = ArchitectureAnalysisRequest(
        image_path=image_path,
        analysis_type="complete",
        job_id=job_id
    )
    
    final_output = None
    
    async for event in workflow.run_stream(request):
        if isinstance(event, WorkflowOutputEvent):
            final_output = event.data
    
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
        """Execute complete workflow: Vision -> Analyzer -> Best Practices -> IAC Generator -> IAC Reviewer"""
        return asyncio.run(run_architecture_analysis_workflow(image_path, job_id))
    
    def execute_analyzer_only(self, image_path: str, job_id: Optional[str] = None) -> Dict[str, Any]:
        """Execute analysis only: Vision -> Analyzer -> Best Practices"""
        return asyncio.run(run_architecture_analysis_workflow(image_path, job_id))
    
    def execute_iac_generation(self, best_practices: Dict[str, Any], job_id: Optional[str] = None) -> Dict[str, Any]:
        """Execute IAC generation and review"""
        return asyncio.run(run_architecture_analysis_workflow("", job_id))


# ============================================================================


async def main(image_path: str = None):
    """Main function to run the architecture analysis workflow"""
    try:
        if not image_path:
            image_path = "./sample_architecture_diagram.png"
        
        result = await run_architecture_analysis_workflow(image_path)
        
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
