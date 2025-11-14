"""
ServiceNow Update Agent
Updates ServiceNow incident with root cause analysis and remediation actions.
"""
import logging
import httpx
import json
from datetime import datetime
from typing import Never
from agent_framework import Executor, ChatMessage, WorkflowContext, handler
from agent_framework_azure_ai import AzureAIAgentClient
from azure.identity.aio import DefaultAzureCredential
from models import RemediationExecution, IncidentResolution
from config import config

logger = logging.getLogger(__name__)


class ServiceNowUpdateAgent(Executor):
    """
    Agent that performs root cause analysis and updates ServiceNow incidents.
    
    This agent:
    1. Receives remediation execution results
    2. Performs root cause analysis based on successful actions
    3. Creates incident resolution summary
    4. Updates ServiceNow incident with RCA and resolution
    5. Closes the workflow
    """
    
    def __init__(self, credential: DefaultAzureCredential, agent_id: str = "servicenow_update_agent"):
        """
        Initialize the ServiceNow Update Agent.
        
        Args:
            credential: Azure credential for authentication
            agent_id: Unique identifier for this agent
        """
        self.chat_client = AzureAIAgentClient(
            project_endpoint=config.azure_ai.project_endpoint,
            model_deployment_name=config.azure_ai.model_deployment_name,
            async_credential=credential,
            agent_name="ServiceNowUpdateAgent"
        )
        
        self.instructions = """You are an expert IT incident analyst specializing in root cause analysis 
        and incident documentation. Your role is to analyze remediation execution results and create 
        comprehensive incident resolutions for ServiceNow.

        When creating an incident resolution, you must:
        
        1. **Analyze Execution Results**: Review all actions performed, their success/failure status, 
           and any outputs or errors.
        
        2. **Determine Root Cause**: Based on which actions succeeded and which failed, identify the 
           most likely root cause. Be specific and technical.
           Examples of good RCA:
           - "Memory leak in application pool caused by unclosed database connections"
           - "Database connection pool exhausted due to long-running queries"
           - "Disk space exhaustion from unrotated application logs"
           Bad RCA:
           - "Application error" (too vague)
           - "Server issue" (not specific)
        
        3. **Summarize Remediation**: Create a clear summary of what was done to resolve the incident.
           Focus on the successful actions and their impact.
        
        4. **Write Resolution Notes**: Provide comprehensive resolution notes that include:
           - Root cause explanation
           - Actions taken to resolve
           - Validation of resolution
           - Recommendations for prevention
        
        5. **Be Honest About Failures**: If remediation failed or was only partially successful, 
           clearly state this and recommend next steps.

        **Output Format**: You MUST respond with valid JSON:
        
        ```json
        {
            "root_cause": "Specific, technical root cause description",
            "remediation_summary": "Clear summary of actions taken (2-3 sentences)",
            "resolution_notes": "Comprehensive resolution notes including RCA, actions, validation, and recommendations"
        }
        ```
        
        **Important Rules**:
        - Always return valid JSON - no markdown, no extra text
        - Root cause should be a single, specific technical issue
        - Remediation summary should be concise but complete
        - Resolution notes should be detailed enough for future reference
        - If remediation failed, recommend manual intervention steps
        - Include any warnings or follow-up actions needed
        """
        
        self.http_client = httpx.AsyncClient(timeout=60.0)
        super().__init__(id=agent_id)
        logger.info(f"ServiceNow Update Agent initialized: {agent_id}")
    
    @handler
    async def update_incident(
        self, 
        execution: RemediationExecution, 
        ctx: WorkflowContext[Never, IncidentResolution]
    ) -> None:
        """
        Perform RCA and update ServiceNow incident.
        
        Args:
            execution: Remediation execution results
            ctx: Workflow context to yield final resolution
        """
        try:
            logger.info(
                f"Creating resolution for incident {execution.incident_id} "
                f"(execution: {execution.execution_id})"
            )
            
            # Prepare execution summary for agent
            execution_summary = f"""
Execution ID: {execution.execution_id}
Overall Status: {execution.overall_status}
Started: {execution.started_at}
Completed: {execution.completed_at}
Duration: {(execution.completed_at - execution.started_at).total_seconds():.1f} seconds

Actions Performed:
"""
            for i, result in enumerate(execution.results, 1):
                status_icon = "✅" if result.status == "success" else "❌"
                execution_summary += f"\n{i}. {status_icon} Action ID: {result.action_id}"
                execution_summary += f"\n   Status: {result.status}"
                execution_summary += f"\n   Duration: {(result.end_time - result.start_time).total_seconds():.2f}s"
                if result.output:
                    execution_summary += f"\n   Output: {result.output[:200]}"
                if result.error_message:
                    execution_summary += f"\n   Error: {result.error_message[:200]}"
                execution_summary += "\n"
            
            # Create prompt for RCA agent
            prompt = f"""
            Analyze the following remediation execution results and provide a comprehensive incident resolution:

            {execution_summary}

            Based on these results, determine the root cause and document the resolution.
            """
            
            messages = [ChatMessage(role="user", text=prompt)]
            
            # Run the agent
            response = await self.chat_client.create_agent(
                instructions=self.instructions
            ).run(messages)
            
            response_text = response.messages[-1].contents[-1].text
            
            logger.info(f"RCA agent response: {response_text[:200]}...")
            
            # Parse JSON response
            try:
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0].strip()
                
                resolution_data = json.loads(response_text)
                
                # Create IncidentResolution object
                resolution = IncidentResolution(
                    incident_id=execution.incident_id,
                    root_cause=resolution_data["root_cause"],
                    remediation_summary=resolution_data["remediation_summary"],
                    actions_performed=execution.results,
                    resolution_notes=resolution_data["resolution_notes"],
                    resolved_at=datetime.utcnow()
                )
                
                logger.info(
                    f"Resolution created for {execution.incident_id}. "
                    f"Root cause: {resolution.root_cause[:100]}..."
                )
                
                # Update ServiceNow incident
                await self._update_servicenow_incident(resolution)
                
                # Yield final workflow output
                await ctx.yield_output(resolution)
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse RCA agent response as JSON: {e}")
                logger.error(f"Response text: {response_text}")
                raise ValueError(f"RCA agent returned invalid JSON: {str(e)}")
                
        except Exception as e:
            logger.error(f"Error updating ServiceNow incident: {str(e)}", exc_info=True)
            raise
    
    async def _update_servicenow_incident(self, resolution: IncidentResolution) -> bool:
        """
        Update ServiceNow incident with resolution details.
        
        Args:
            resolution: Incident resolution data
            
        Returns:
            True if update successful, False otherwise
        """
        try:
            # ServiceNow REST API endpoint
            url = f"{config.servicenow.instance_url}/api/now/table/incident/{resolution.incident_id}"
            
            # Prepare update payload
            payload = {
                "close_code": "Solved (Permanently)",
                "close_notes": resolution.resolution_notes,
                "resolution_code": "Automated Remediation",
                "resolved_at": resolution.resolved_at.isoformat(),
                "state": "6",  # Resolved state in ServiceNow
                "work_notes": f"""
Automated Remediation Completed

Root Cause:
{resolution.root_cause}

Remediation Summary:
{resolution.remediation_summary}

Actions Performed: {len(resolution.actions_performed)}
- Successful: {len([a for a in resolution.actions_performed if a.status == 'success'])}
- Failed: {len([a for a in resolution.actions_performed if a.status == 'failed'])}

Full resolution details have been documented in close_notes.
"""
            }
            
            # ServiceNow authentication
            auth = (config.servicenow.api_user, config.servicenow.api_password)
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            
            logger.info(f"Updating ServiceNow incident: {resolution.incident_id}")
            
            response = await self.http_client.patch(
                url,
                json=payload,
                auth=auth,
                headers=headers
            )
            
            if response.status_code in [200, 201]:
                logger.info(f"ServiceNow incident {resolution.incident_id} updated successfully")
                return True
            else:
                logger.error(
                    f"Failed to update ServiceNow incident: {response.status_code} - {response.text}"
                )
                return False
                
        except Exception as e:
            logger.error(f"Error updating ServiceNow: {str(e)}", exc_info=True)
            return False
    
    async def close(self):
        """Clean up HTTP client."""
        await self.http_client.aclose()


async def create_servicenow_update_agent(
    credential: DefaultAzureCredential
) -> ServiceNowUpdateAgent:
    """
    Factory function to create a ServiceNow Update Agent.
    
    Args:
        credential: Azure credential for authentication
        
    Returns:
        Configured ServiceNowUpdateAgent instance
    """
    return ServiceNowUpdateAgent(credential)
