"""
Incident Analysis Agent
Receives ServiceNow incident data and analyzes it to create a structured summary.
"""
import logging
from typing import Never
from agent_framework import Executor, ChatMessage, WorkflowContext, handler
from agent_framework_azure_ai import AzureAIAgentClient
from azure.identity.aio import DefaultAzureCredential
from models import ServiceNowIncident, IncidentSummary, IncidentStatus
from config import config
import json
from datetime import datetime

logger = logging.getLogger(__name__)


class IncidentAnalysisAgent(Executor):
    """
    Agent that analyzes ServiceNow incidents and creates structured summaries.
    
    This agent receives raw incident data from ServiceNow webhooks,
    analyzes the content, identifies symptoms and potential root causes,
    and formats the information for the remediation planning agent.
    """
    
    def __init__(self, credential: DefaultAzureCredential, agent_id: str = "incident_analysis_agent"):
        """
        Initialize the Incident Analysis Agent.
        
        Args:
            credential: Azure credential for authentication
            agent_id: Unique identifier for this agent
        """
        # Create the AI agent client with Azure AI Foundry
        self.chat_client = AzureAIAgentClient(
            project_endpoint=config.azure_ai.project_endpoint,
            model_deployment_name=config.azure_ai.model_deployment_name,
            async_credential=credential,
            agent_name="IncidentAnalysisAgent"
        )
        
        # Define agent instructions for incident analysis
        self.instructions = """You are an expert IT incident analyst with deep knowledge of infrastructure, 
        applications, and cloud services. Your role is to analyze ServiceNow incidents and create structured 
        summaries that enable effective remediation.

        When analyzing an incident, you must:
        
        1. **Understand the Issue**: Read all incident details carefully including description, priority, 
           affected configuration items, and any additional comments.
        
        2. **Identify Symptoms**: Extract and list all observable symptoms (e.g., "users unable to login", 
           "API returning 500 errors", "database connection timeouts").
        
        3. **Assess Severity**: Determine the true severity based on business impact, number of users affected, 
           and service criticality. Categories: CRITICAL, HIGH, MODERATE, LOW.
        
        4. **Identify Affected Service**: Clearly identify the primary service, application, or infrastructure 
           component that is impacted (e.g., "Customer Portal Web App", "Production SQL Database", 
           "Payment Processing API").
        
        5. **Hypothesize Root Causes**: Based on the symptoms and affected service, list 2-4 potential root 
           causes. Be specific (e.g., "Memory leak causing OOM errors" not just "application error").
        
        6. **Evaluate Business Impact**: Describe the business impact in clear terms 
           (e.g., "Revenue loss: customers cannot complete purchases", 
           "Reputation damage: external-facing service unavailable").
        
        7. **Create Summary**: Write a concise 2-3 sentence summary that captures the essence of the issue.

        **Output Format**: You MUST respond with a valid JSON object using this exact structure:
        
        ```json
        {
            "incident_id": "ServiceNow sys_id",
            "incident_number": "INC number",
            "summary": "Concise 2-3 sentence summary of the incident",
            "severity": "CRITICAL|HIGH|MODERATE|LOW",
            "affected_service": "Primary service or component name",
            "symptoms": ["symptom1", "symptom2", "symptom3"],
            "potential_root_causes": ["cause1", "cause2", "cause3"],
            "business_impact": "Clear description of business impact"
        }
        ```
        
        **Important Rules**:
        - Always return valid JSON - no markdown, no extra text
        - Include all required fields
        - Be specific and actionable in your analysis
        - Focus on technical accuracy
        - Symptoms should be observable, measurable issues
        - Root causes should be specific technical hypotheses
        """
        
        super().__init__(id=agent_id)
        logger.info(f"Incident Analysis Agent initialized: {agent_id}")
    
    @handler
    async def analyze_incident(
        self, 
        incident_data: dict, 
        ctx: WorkflowContext[IncidentSummary]
    ) -> None:
        """
        Analyze a ServiceNow incident and create a structured summary.
        
        Args:
            incident_data: Raw ServiceNow incident data dictionary
            ctx: Workflow context to send the incident summary to next agent
        """
        try:
            logger.info(f"Starting incident analysis for: {incident_data.get('number', 'Unknown')}")
            
            # Parse incident data
            incident = ServiceNowIncident(**incident_data)
            
            # Create prompt with incident details
            incident_text = f"""
            Incident Number: {incident.number}
            Priority: {incident.priority.value}
            Urgency: {incident.urgency}
            Impact: {incident.impact}
            
            Short Description: {incident.short_description}
            
            Detailed Description:
            {incident.description or 'No detailed description provided'}
            
            Category: {incident.category or 'Not specified'}
            Subcategory: {incident.subcategory or 'Not specified'}
            
            Affected Configuration Item: {incident.configuration_item or 'Not specified'}
            
            Additional Comments:
            {incident.additional_comments or 'No additional comments'}
            
            Opened At: {incident.opened_at}
            """
            
            # Create messages for the agent
            messages = [
                ChatMessage(
                    role="user",
                    text=f"Analyze this ServiceNow incident and provide a structured summary:\n\n{incident_text}"
                )
            ]
            
            # Run the agent using the chat client
            response = await self.chat_client.create_agent(
                instructions=self.instructions
            ).run(messages)
            
            # Extract the response text
            response_text = response.messages[-1].contents[-1].text
            
            logger.info(f"Agent response: {response_text[:200]}...")
            
            # Parse JSON response
            try:
                # Clean up response if it has markdown code blocks
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0].strip()
                
                analysis_result = json.loads(response_text)
                
                # Create IncidentSummary object
                incident_summary = IncidentSummary(
                    incident_id=incident.sys_id,
                    incident_number=incident.number,
                    summary=analysis_result["summary"],
                    severity=analysis_result["severity"],
                    affected_service=analysis_result["affected_service"],
                    symptoms=analysis_result["symptoms"],
                    potential_root_causes=analysis_result["potential_root_causes"],
                    business_impact=analysis_result["business_impact"],
                    analyzed_at=datetime.utcnow()
                )
                
                logger.info(
                    f"Incident analysis completed for {incident.number}: "
                    f"Severity={incident_summary.severity}, "
                    f"Service={incident_summary.affected_service}"
                )
                
                # Send the incident summary to the next agent in the workflow
                await ctx.send_message(incident_summary)
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse agent response as JSON: {e}")
                logger.error(f"Response text: {response_text}")
                raise ValueError(f"Agent returned invalid JSON: {str(e)}")
                
        except Exception as e:
            logger.error(f"Error analyzing incident: {str(e)}", exc_info=True)
            raise


async def create_incident_analysis_agent(
    credential: DefaultAzureCredential
) -> IncidentAnalysisAgent:
    """
    Factory function to create an Incident Analysis Agent.
    
    Args:
        credential: Azure credential for authentication
        
    Returns:
        Configured IncidentAnalysisAgent instance
    """
    return IncidentAnalysisAgent(credential)
