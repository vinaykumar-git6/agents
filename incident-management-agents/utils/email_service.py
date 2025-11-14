"""
Email notification service using Azure Communication Services.
Sends approval requests and remediation summaries.
"""
import logging
from typing import Optional
from azure.communication.email import EmailClient
from config import config

logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending email notifications."""
    
    def __init__(self):
        """Initialize Azure Communication Services email client."""
        self.email_client = EmailClient.from_connection_string(
            config.communication.connection_string
        )
        self.sender_email = config.communication.sender_email
        
        logger.info("Email service initialized successfully")
    
    async def send_approval_request_email(
        self,
        recipients: list[str],
        incident_number: str,
        incident_summary: str,
        remediation_plan: str,
        approval_url: str
    ) -> bool:
        """
        Send approval request email to designated approvers.
        
        Args:
            recipients: List of recipient email addresses
            incident_number: ServiceNow incident number
            incident_summary: Brief summary of the incident
            remediation_plan: Detailed remediation plan
            approval_url: URL to approve/reject the plan
            
        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            subject = f"[ACTION REQUIRED] Remediation Approval - {incident_number}"
            
            html_content = f"""
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
                    .header {{ background-color: #0078d4; color: white; padding: 20px; }}
                    .content {{ padding: 20px; }}
                    .incident-box {{ background-color: #f3f2f1; padding: 15px; margin: 10px 0; border-left: 4px solid #0078d4; }}
                    .plan-box {{ background-color: #fff4ce; padding: 15px; margin: 10px 0; border-left: 4px solid #ffc107; }}
                    .button {{ display: inline-block; padding: 12px 24px; margin: 10px 5px; text-decoration: none; border-radius: 4px; font-weight: bold; }}
                    .approve {{ background-color: #107c10; color: white; }}
                    .reject {{ background-color: #d13438; color: white; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>🚨 Incident Remediation Approval Required</h1>
                </div>
                <div class="content">
                    <p>A remediation plan has been generated for incident <strong>{incident_number}</strong> and requires your approval before execution.</p>
                    
                    <div class="incident-box">
                        <h3>📋 Incident Summary</h3>
                        <p>{incident_summary}</p>
                    </div>
                    
                    <div class="plan-box">
                        <h3>🔧 Proposed Remediation Plan</h3>
                        <pre>{remediation_plan}</pre>
                    </div>
                    
                    <h3>⏱️ Action Required</h3>
                    <p>Please review the remediation plan and take action within {config.approval.timeout_minutes} minutes.</p>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{approval_url}?action=approve" class="button approve">✅ APPROVE PLAN</a>
                        <a href="{approval_url}?action=reject" class="button reject">❌ REJECT PLAN</a>
                    </div>
                    
                    <p style="color: #605e5c; font-size: 0.9em; margin-top: 30px;">
                        <strong>Note:</strong> If no action is taken within {config.approval.timeout_minutes} minutes, 
                        this request will expire and the incident will require manual intervention.
                    </p>
                </div>
            </body>
            </html>
            """
            
            message = {
                "senderAddress": self.sender_email,
                "recipients": {
                    "to": [{"address": email} for email in recipients]
                },
                "content": {
                    "subject": subject,
                    "html": html_content
                }
            }
            
            poller = self.email_client.begin_send(message)
            result = poller.result()
            
            logger.info(
                f"Approval email sent successfully to {len(recipients)} recipients "
                f"for incident {incident_number}"
            )
            return True
            
        except Exception as e:
            logger.error(f"Failed to send approval email: {str(e)}")
            return False
    
    async def send_remediation_summary_email(
        self,
        recipients: list[str],
        incident_number: str,
        incident_summary: str,
        actions_performed: list[dict],
        overall_status: str,
        resolution_notes: str
    ) -> bool:
        """
        Send remediation summary email after completion.
        
        Args:
            recipients: List of recipient email addresses
            incident_number: ServiceNow incident number
            incident_summary: Brief summary of the incident
            actions_performed: List of actions performed
            overall_status: Overall execution status
            resolution_notes: Resolution and RCA notes
            
        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            status_icon = "✅" if overall_status == "success" else "⚠️"
            subject = f"{status_icon} Remediation Complete - {incident_number}"
            
            # Format actions table
            actions_html = "<table style='width:100%; border-collapse: collapse; margin: 10px 0;'>"
            actions_html += "<tr style='background-color: #f3f2f1;'>"
            actions_html += "<th style='padding: 10px; text-align: left; border: 1px solid #ddd;'>Action</th>"
            actions_html += "<th style='padding: 10px; text-align: left; border: 1px solid #ddd;'>Status</th>"
            actions_html += "<th style='padding: 10px; text-align: left; border: 1px solid #ddd;'>Duration</th>"
            actions_html += "</tr>"
            
            for action in actions_performed:
                status_badge = "✅ Success" if action["status"] == "success" else "❌ Failed"
                duration = f"{action.get('duration_seconds', 0):.2f}s"
                actions_html += f"<tr style='border: 1px solid #ddd;'>"
                actions_html += f"<td style='padding: 10px;'>{action['description']}</td>"
                actions_html += f"<td style='padding: 10px;'>{status_badge}</td>"
                actions_html += f"<td style='padding: 10px;'>{duration}</td>"
                actions_html += "</tr>"
            
            actions_html += "</table>"
            
            html_content = f"""
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
                    .header {{ background-color: #107c10; color: white; padding: 20px; }}
                    .content {{ padding: 20px; }}
                    .summary-box {{ background-color: #f3f2f1; padding: 15px; margin: 10px 0; border-left: 4px solid #107c10; }}
                    .resolution-box {{ background-color: #e1dfdd; padding: 15px; margin: 10px 0; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>{status_icon} Incident Remediation Summary</h1>
                </div>
                <div class="content">
                    <p>Automated remediation has been completed for incident <strong>{incident_number}</strong>.</p>
                    
                    <div class="summary-box">
                        <h3>📋 Incident</h3>
                        <p>{incident_summary}</p>
                    </div>
                    
                    <h3>🔧 Actions Performed</h3>
                    {actions_html}
                    
                    <div class="resolution-box">
                        <h3>📝 Root Cause Analysis & Resolution</h3>
                        <p style="white-space: pre-wrap;">{resolution_notes}</p>
                    </div>
                    
                    <p style="margin-top: 30px;">
                        <strong>Overall Status:</strong> {overall_status.upper()}
                    </p>
                    
                    <p style="color: #605e5c; font-size: 0.9em; margin-top: 30px;">
                        This is an automated notification from the Incident Management Agent System.
                        The incident has been updated in ServiceNow with the resolution details.
                    </p>
                </div>
            </body>
            </html>
            """
            
            message = {
                "senderAddress": self.sender_email,
                "recipients": {
                    "to": [{"address": email} for email in recipients]
                },
                "content": {
                    "subject": subject,
                    "html": html_content
                }
            }
            
            poller = self.email_client.begin_send(message)
            result = poller.result()
            
            logger.info(
                f"Remediation summary email sent successfully to {len(recipients)} recipients "
                f"for incident {incident_number}"
            )
            return True
            
        except Exception as e:
            logger.error(f"Failed to send remediation summary email: {str(e)}")
            return False
    
    def close(self):
        """Close email client connections."""
        logger.info("Email service closed")


# Global email service instance
email_service = EmailService()
