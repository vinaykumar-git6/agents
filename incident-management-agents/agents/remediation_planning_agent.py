"""
Incident Remediation Planning Agent
Searches knowledge base and creates remediation plans based on incident analysis.
"""
import logging
import json
import uuid
from datetime import datetime
from typing import Never
from agent_framework import Executor, ChatMessage, WorkflowContext, handler
from agent_framework_azure_ai import AzureAIAgentClient
from azure.identity.aio import DefaultAzureCredential
from models import IncidentSummary, RemediationPlan, RemediationAction
from utils.search_client import search_service
from config import config

logger = logging.getLogger(__name__)


class RemediationPlanningAgent(Executor):
    """
    Agent that creates remediation plans based on incident analysis and knowledge base.
    
    This agent:
    1. Receives incident summary from analysis agent
    2. Searches Azure AI Search knowledge base for similar incidents
    3. Creates a structured remediation plan with specific actions
    4. Assigns risk levels and duration estimates
    """
    
    def __init__(self, credential: DefaultAzureCredential, agent_id: str = "remediation_planning_agent"):
        """
        Initialize the Remediation Planning Agent.
        
        Args:
            credential: Azure credential for authentication
            agent_id: Unique identifier for this agent
        """
        self.chat_client = AzureAIAgentClient(
            project_endpoint=config.azure_ai.project_endpoint,
            model_deployment_name=config.azure_ai.model_deployment_name,
            async_credential=credential,
            agent_name="RemediationPlanningAgent"
        )
        
        self.instructions = """You are an expert remediation planner with deep knowledge of IT operations, 
        infrastructure management, and incident resolution procedures. Your role is to create detailed, 
        actionable remediation plans based on incident analysis and knowledge base articles.

        When creating a remediation plan, you must:
        
        1. **Review Incident Summary**: Understand the symptoms, severity, affected service, and potential 
           root causes.
        
        2. **Analyze Knowledge Base Results**: Review the provided KB articles for similar incidents. 
           Extract relevant remediation steps, validation procedures, and prerequisites.
        
        3. **Create Ordered Actions**: Define a sequence of specific remediation actions. Each action should be:
           - **Actionable**: Clear enough for automation or manual execution
           - **Targeted**: Specify the exact Azure resource or component
           - **Parameterized**: Include all necessary parameters
           - **Validated**: Include validation steps
        
        4. **Assess Risk**: For each action, determine risk level:
           - **LOW**: Read-only operations, restarts of non-critical services
           - **MEDIUM**: Service restarts, scaling operations, configuration changes
           - **HIGH**: Data operations, production database changes, deletion operations
        
        5. **Estimate Duration**: Provide realistic time estimates in minutes for each action.
        
        6. **Calculate Confidence**: Based on KB match quality and clarity of root cause, assign a 
           confidence score (0.0 to 1.0).

        **Action Types** (use these exactly):
        - restart_service: Restart an application, service, or VM
        - scale_resource: Scale up/down/out/in Azure resources
        - clear_cache: Clear application or database cache
        - update_config: Update configuration settings
        - restart_vm: Restart a virtual machine
        - restart_app_service: Restart an Azure App Service
        - run_diagnostic: Run diagnostic commands
        - apply_patch: Apply software patches
        - rollback_deployment: Rollback to previous deployment
        - clear_logs: Clear or rotate logs
        - reset_connection_pool: Reset database connections

        **Output Format**: You MUST respond with valid JSON:
        
        ```json
        {
            "summary": "Brief plan summary (1-2 sentences)",
            "actions": [
                {
                    "action_id": "unique-id",
                    "action_type": "one of the action types above",
                    "target_resource": "specific Azure resource name or identifier",
                    "description": "Clear description of what this action does",
                    "parameters": {
                        "key1": "value1",
                        "key2": "value2"
                    },
                    "estimated_duration_minutes": 5,
                    "risk_level": "LOW|MEDIUM|HIGH"
                }
            ],
            "estimated_total_duration_minutes": 15,
            "knowledge_base_references": ["KB001", "KB002"],
            "confidence_score": 0.85
        }
        ```
        
        **Important Rules**:
        - Always return valid JSON - no markdown, no extra text
        - Actions must be in the correct execution order
        - Include rollback steps if risk is HIGH
        - Be conservative with confidence scores (0.7-0.9 is typical)
        - Specify exact resource names when provided in incident
        - Include validation parameters to confirm success
        """
        
        super().__init__(id=agent_id)
        logger.info(f"Remediation Planning Agent initialized: {agent_id}")
    
    @handler
    async def create_plan(
        self, 
        incident_summary: IncidentSummary, 
        ctx: WorkflowContext[RemediationPlan]
    ) -> None:
        """
        Create a remediation plan based on incident analysis.
        
        Args:
            incident_summary: Analyzed incident summary
            ctx: Workflow context to send remediation plan to next agent
        """
        try:
            logger.info(
                f"Creating remediation plan for incident {incident_summary.incident_number}"
            )
            
            # Search knowledge base for similar incidents
            kb_results = search_service.search_similar_incidents(
                symptoms=incident_summary.symptoms,
                affected_service=incident_summary.affected_service,
                top=5
            )
            
            # Format KB results for agent
            kb_context = "\n\n".join([
                f"KB Article {i+1} (ID: {doc['id']}, Score: {doc.get('score', 0):.2f}):\n"
                f"Title: {doc['title']}\n"
                f"Category: {doc.get('category', 'N/A')}\n"
                f"Root Cause: {doc.get('root_cause', 'N/A')}\n"
                f"Remediation Steps:\n" + 
                "\n".join([f"  {j+1}. {step}" for j, step in enumerate(doc.get('remediation_steps', []))]) +
                f"\n\nValidation Steps:\n" +
                "\n".join([f"  - {step}" for step in doc.get('validation_steps', [])])
                for i, doc in enumerate(kb_results)
            ])
            
            if not kb_context:
                kb_context = "No matching knowledge base articles found. Use general best practices."
            
            # Create prompt
            prompt = f"""
            INCIDENT SUMMARY:
            Incident: {incident_summary.incident_number}
            Severity: {incident_summary.severity}
            Affected Service: {incident_summary.affected_service}
            Summary: {incident_summary.summary}
            
            Symptoms:
            {chr(10).join(['- ' + s for s in incident_summary.symptoms])}
            
            Potential Root Causes:
            {chr(10).join(['- ' + c for c in incident_summary.potential_root_causes])}
            
            Business Impact: {incident_summary.business_impact}
            
            ---
            
            KNOWLEDGE BASE RESULTS:
            {kb_context}
            
            ---
            
            Based on the incident summary and knowledge base articles, create a detailed remediation plan 
            with specific, executable actions. Focus on Azure services and automation-friendly steps.
            """
            
            messages = [ChatMessage(role="user", text=prompt)]
            
            # Run the agent
            response = await self.chat_client.create_agent(
                instructions=self.instructions
            ).run(messages)
            
            response_text = response.messages[-1].contents[-1].text
            
            logger.info(f"Planning agent response: {response_text[:200]}...")
            
            # Parse JSON response
            try:
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0].strip()
                
                plan_data = json.loads(response_text)
                
                # Create RemediationAction objects
                actions = []
                for action_data in plan_data["actions"]:
                    action = RemediationAction(
                        action_id=action_data.get("action_id", str(uuid.uuid4())),
                        action_type=action_data["action_type"],
                        target_resource=action_data["target_resource"],
                        description=action_data["description"],
                        parameters=action_data.get("parameters", {}),
                        estimated_duration_minutes=action_data["estimated_duration_minutes"],
                        risk_level=action_data["risk_level"]
                    )
                    actions.append(action)
                
                # Create RemediationPlan object
                plan = RemediationPlan(
                    incident_id=incident_summary.incident_id,
                    plan_id=str(uuid.uuid4()),
                    summary=plan_data["summary"],
                    actions=actions,
                    estimated_total_duration_minutes=plan_data["estimated_total_duration_minutes"],
                    knowledge_base_references=[doc["id"] for doc in kb_results][:3],
                    confidence_score=plan_data["confidence_score"],
                    created_at=datetime.utcnow()
                )
                
                logger.info(
                    f"Remediation plan created for {incident_summary.incident_number}: "
                    f"{len(actions)} actions, confidence={plan.confidence_score:.2f}"
                )
                
                # Send plan to next agent
                await ctx.send_message(plan)
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse planning agent response as JSON: {e}")
                logger.error(f"Response text: {response_text}")
                raise ValueError(f"Planning agent returned invalid JSON: {str(e)}")
                
        except Exception as e:
            logger.error(f"Error creating remediation plan: {str(e)}", exc_info=True)
            raise


async def create_remediation_planning_agent(
    credential: DefaultAzureCredential
) -> RemediationPlanningAgent:
    """
    Factory function to create a Remediation Planning Agent.
    
    Args:
        credential: Azure credential for authentication
        
    Returns:
        Configured RemediationPlanningAgent instance
    """
    return RemediationPlanningAgent(credential)
