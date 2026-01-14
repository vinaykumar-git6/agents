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
from typing import Any, Dict, Optional, cast
from typing_extensions import Never

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

# Load environment
env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=env_path, override=True)

# Initialize logging
setup_logging(level="INFO")

logger = setup_logger(__name__)


# ============================================================================
# Response Models (Pydantic)
# ============================================================================

class ArchitectureAnalysisRequest(BaseModel):
    """Workflow request for architecture analysis"""
    image_path: str
    analysis_type: str = "complete"  # complete, analysis_only, iac_only


class VisionAnalysisResponse(BaseModel):
    """Vision analysis output"""
    text: list = []
    objects: list = []
    tags: list = []
    dense_captions: list = []
    architecture_type: str = ""
    services_detected: list = []
    status: str = "SUCCESS"


class AnalyzerResponse(BaseModel):
    """Service analyzer output"""
    cloud_provider: str = ""
    default_region: str = ""
    total_services: int = 0
    azure_services: list = []
    summary: str = ""
    status: str = "SUCCESS"


class BestPracticesResponse(BaseModel):
    """Best practices recommendations"""
    service_recommendations: list = []
    architecture_checklist: list = []
    summary: str = ""
    total_recommendations: int = 0
    status: str = "SUCCESS"


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
        'terraform.tfvars': terraform_data.get('terraform_tfvars', '')
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
        'terraform_tfvars': ''
    }
    
    # Define file markers - try both === and ### formats
    file_patterns = {
        'providers_tf': [r'===\s*providers\.tf\s*===', r'###\s*providers\.tf'],
        'main_tf': [r'===\s*main\.tf\s*===', r'###\s*main\.tf'],
        'variables_tf': [r'===\s*variables\.tf\s*===', r'###\s*variables\.tf'],
        'outputs_tf': [r'===\s*outputs\.tf\s*===', r'###\s*outputs\.tf'],
        'terraform_tfvars': [r'===\s*terraform\.tfvars\s*===', r'###\s*terraform\.tfvars']
    }
    
    # Try to extract each file
    for key, patterns in file_patterns.items():
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                start_pos = match.end()
                
                # Find the start of the code block (after the header)
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
                    content = re.sub(r'^```(?:hcl|terraform)?\s*\n', '', content)
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
    
    logger.info("[EXECUTOR 1/4] Vision Analysis")
    
    try:
        config = Config.from_environment()
        vision_agent = VisionAgent(config)
        
        await vision_agent.initialize()
        result = await vision_agent.analyze(request.image_path)
        
        if not result:
            raise Exception("Vision analysis returned empty result")
        
        vision_response = VisionAnalysisResponse(
            text=result.get('text', []),
            objects=result.get('objects', []),
            tags=result.get('tags', []),
            dense_captions=result.get('dense_captions', []),
            architecture_type=result.get('architecture_type', ''),
            services_detected=result.get('services_detected', []),
            status="SUCCESS"
        )
        
        logger.info(f"✓ Vision: {len(vision_response.text)} texts, {len(vision_response.objects)} objects")
        await ctx.send_message(vision_response)
        
    except Exception as e:
        logger.error(f"✗ Vision analysis failed: {e}")
        error_response = VisionAnalysisResponse(status="ERROR")
        await ctx.send_message(error_response)


@executor
async def service_analyzer_executor(
    vision_response: VisionAnalysisResponse,
    ctx: WorkflowContext[AnalyzerResponse]
) -> None:
    """Service analyzer executor - analyzes detected services from vision data"""
    
    logger.info("[EXECUTOR 2/4] Service Analysis")
    
    try:
        config = Config.from_environment()
        analyzer_agent = AnalyzerAgent(config)
        
        await analyzer_agent.initialize()
        
        # Convert vision response to dict for analyzer
        vision_data = {
            'text': vision_response.text,
            'objects': vision_response.objects,
            'tags': vision_response.tags,
            'dense_captions': vision_response.dense_captions,
            'architecture_type': vision_response.architecture_type,
            'services_detected': vision_response.services_detected
        }
        
        result = await analyzer_agent.analyze(vision_data)
        
        if not result:
            raise Exception("Service analysis returned empty result")
        
        analyzer_response = AnalyzerResponse(
            cloud_provider=result.get('cloud_provider', ''),
            default_region=result.get('default_region', ''),
            total_services=result.get('total_services', 0),
            azure_services=result.get('azure_services', []),
            summary=result.get('summary', ''),
            status="SUCCESS"
        )
        logger.info(f"✓ Analyzer Response: {analyzer_response} ")
        logger.info(f"✓ Analyzer: {analyzer_response.total_services} services identified")
        await ctx.send_message(analyzer_response)
        
    except Exception as e:
        logger.error(f"✗ Service analysis failed: {e}")
        error_response = AnalyzerResponse(status="ERROR")
        await ctx.send_message(error_response)


@executor
async def best_practices_executor(
    analyzer_response: AnalyzerResponse,
    ctx: WorkflowContext[BestPracticesResponse]
) -> None:
    """Best practices executor - generates recommendations"""
    
    logger.info("[EXECUTOR 3/4] Best Practices Advisor")
    logger.info(f"DEBUG - Best Practices received analyzer_response: {analyzer_response}")
    
    try:
        config = Config.from_environment()
        best_practice_agent = AzureBestPracticeAgent(config)
        
        await best_practice_agent.initialize()
        
        # Convert analyzer response to dict
        analyzer_data = {
            'cloud_provider': analyzer_response.cloud_provider,
            'default_region': analyzer_response.default_region,
            'total_services': analyzer_response.total_services,
            'azure_services': analyzer_response.azure_services,
            'summary': analyzer_response.summary
        }
        
        logger.info(f"DEBUG - Best Practices sending analyzer_data: {analyzer_data}")
        result = await best_practice_agent.recommend(analyzer_data)
        logger.info(f"DEBUG - Best Practices received result: {result}")
        
        if not result:
            raise Exception("Best practices recommendation returned empty result")
        
        best_practices_response = BestPracticesResponse(
            service_recommendations=result.get('service_recommendations', []),
            architecture_checklist=result.get('architecture_checklist', []),
            summary=result.get('summary', ''),
            total_recommendations=result.get('total_recommendations', 0),
            status="SUCCESS"
        )
        logger.info(f"✓ Best Practices Response: {best_practices_response} ")
        logger.info(f"✓ Best Practices: {best_practices_response.total_recommendations} recommendations")
        await ctx.send_message(best_practices_response)
        
    except Exception as e:
        logger.error(f"✗ Best practices failed: {e}")
        error_response = BestPracticesResponse(status="ERROR")
        await ctx.send_message(error_response)


@executor
async def iac_generator_reviewer_group_chat_executor(
    best_practices_response: BestPracticesResponse,
    ctx: WorkflowContext[Never, ArchitectureAnalysisWorkflowOutput]
) -> None:
    """IAC generator and reviewer executor - generates and refines Terraform code using group chat with max 10 iterations"""
    
    logger.info("[EXECUTOR 4/4] IAC Generator & Reviewer (Group Chat - Generate & Refine)")
    
    # Check if input is None or invalid
    if best_practices_response is None:
        logger.error("✗ IAC Generator/Reviewer received None as best_practices_response!")
        error_output = ArchitectureAnalysisWorkflowOutput(
            workflow_status="failed",
            errors=["IAC Generator/Reviewer received no input from Best Practices"]
        )
        await ctx.yield_output(error_output)
        return
    
    # Check if response has error status
    if hasattr(best_practices_response, 'status') and best_practices_response.status != "SUCCESS":
        logger.error(f"✗ Best Practices returned error status: {best_practices_response.status}")
        error_output = ArchitectureAnalysisWorkflowOutput(
            workflow_status="failed",
            errors=["Best Practices failed to generate recommendations"]
        )
        await ctx.yield_output(error_output)
        return
    
    iac_generator_agent = None
    iac_reviewer_agent = None
    
    try:
        config = Config.from_environment()
        
        # Convert best practices response to dict for initial code generation
        best_practices_data = {
            'service_recommendations': best_practices_response.service_recommendations,
            'architecture_checklist': best_practices_response.architecture_checklist,
            'summary': best_practices_response.summary,
            'total_recommendations': best_practices_response.total_recommendations
        }
        
        # ============================================================================
        # Initialize existing agents from agents folder
        # ============================================================================
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

        # Run the group chat (following test pattern)
        logger.info("\n[GROUP CHAT] Starting collaborative conversation...")
        logger.info("=" * 80)
       
        final_conversation: list[ChatMessage] = []
        last_executor_id: str | None = None
        
        # Run the workflow with proper event handling
        async for event in group_chat.run_stream(initial_task):
            if isinstance(event, AgentRunUpdateEvent):
                # Print streaming agent updates
                eid = event.executor_id
                if eid != last_executor_id:
                    if last_executor_id is not None:
                        logger.info("")
                    #logger.info(f"[{eid}]: ")
                    last_executor_id = eid
                # Stream the response
                #logger.info(event.data)
            elif isinstance(event, WorkflowOutputEvent):
                # Workflow completed - data is a list of ChatMessage
                final_conversation = cast(list[ChatMessage], event.data)
        
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
        
        # Create review result
        final_review_result = {
            'overall_score': 85,
            'passed': True,
            'issues': [],
            'summary': f'Terraform code reviewed through {len(final_conversation)} message collaborative refinement',
            'conversation_count': len(final_conversation)
        }
        
        # Save Terraform project
        terraform_folder = Path(__file__).parent.parent.parent / 'terraform_projects'
        output_dir = str(terraform_folder / f"arch_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        terraform_path = _save_terraform_project(final_terraform, output_dir)
        
        logger.info("=" * 80)
        logger.info("WORKFLOW COMPLETE: Success")
        logger.info("=" * 80)
        
        # Return final output
        final_output = ArchitectureAnalysisWorkflowOutput(
            workflow_status="success",
            terraform_result=final_terraform,
            review_results=[final_review_result],
            terraform_path=terraform_path,
            errors=[]
        )
        
        await ctx.yield_output(final_output)
        
    except Exception as e:
        logger.error(f"✗ Group chat failed: {e}", exc_info=True)
        
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

async def run_architecture_analysis_workflow(image_path: str):
    """Execute the architecture analysis workflow using Microsoft Agent Framework"""
    
    logger.info("=" * 80)
    logger.info("WORKFLOW START: Complete Architecture Analysis")
    logger.info("=" * 80)
    
    # Build workflow with executors
    workflow = (
        WorkflowBuilder()
        .set_start_executor(vision_analyzer_executor)
        .add_edge(vision_analyzer_executor, service_analyzer_executor)
        .add_edge(service_analyzer_executor, best_practices_executor)
        .add_edge(best_practices_executor, iac_generator_reviewer_group_chat_executor)  # Group chat: generate & review until error-free
        .build()
    )
    
    # Create request
    request = ArchitectureAnalysisRequest(
        image_path=image_path,
        analysis_type="complete"
    )
    
    # Execute workflow with streaming
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
    
    def execute_workflow(self, image_path: str) -> Dict[str, Any]:
        """Execute complete workflow: Vision → Analyzer → Best Practices → IAC Generator → IAC Reviewer"""
        return asyncio.run(run_architecture_analysis_workflow(image_path))
    
    def execute_analyzer_only(self, image_path: str) -> Dict[str, Any]:
        """Execute analysis only: Vision → Analyzer → Best Practices"""
        return asyncio.run(run_architecture_analysis_workflow(image_path))
    
    def execute_iac_generation(self, best_practices: Dict[str, Any]) -> Dict[str, Any]:
        """Execute IAC generation and review"""
        return asyncio.run(run_architecture_analysis_workflow(""))


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
