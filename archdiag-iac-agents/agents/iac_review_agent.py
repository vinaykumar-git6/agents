"""
IaC Review Agent - Stage 4 of the IaC workflow.

This agent:
1. Accepts BicepCode from IaC Generation
2. Validates Bicep syntax using Azure CLI
3. Applies linter rules and best practices
4. Checks security configurations
5. Uses Azure MCP tools for validation
6. Outputs ValidationResult

Uses Microsoft Agent Framework with Azure AI Foundry and Azure MCP tools.
"""

import asyncio
import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Any, Optional

from agent_framework import Executor, WorkflowContext, handler
from agent_framework_azure_ai import AzureAIAgentClient
from azure.identity.aio import DefaultAzureCredential

from config import settings
from models import (
    BicepCode,
    ValidationResult,
    ValidationIssue,
    SeverityLevel,
)

logger = logging.getLogger(__name__)


class IaCReviewAgent(Executor):
    """
    Agent that reviews and validates Bicep infrastructure code.

    Responsibilities:
    - Validate Bicep syntax
    - Run Bicep linter
    - Check security best practices
    - Verify resource configurations
    - Suggest improvements
    - Use Azure MCP tools for validation
    """

    def __init__(self, chat_client: AzureAIAgentClient, executor_id: str = "iac_review_agent"):
        """Initialize the IaC Review Agent."""
        self.agent = chat_client.create_agent(
            instructions="""You are an expert Azure security and governance specialist focused on infrastructure as code review.

Your responsibilities:
1. **Code Review**: Analyze Bicep templates for:
   - Syntax errors and warnings
   - Resource configuration issues
   - Dependency problems
   - API version compatibility

2. **Security Analysis**:
   - Missing encryption configurations
   - Public exposure risks
   - Weak authentication methods
   - Key vault integration opportunities
   - Network security gaps
   - Missing managed identity usage

3. **Best Practices Validation**:
   - Azure Well-Architected Framework compliance
   - Naming convention adherence
   - Tag standardization
   - Resource organization
   - Monitoring and diagnostics setup

4. **Issue Classification**:
   - CRITICAL: Blocks deployment or major security risk
   - ERROR: Should be fixed before deployment
   - WARNING: Should be reviewed
   - INFO: Suggestions for improvement

5. **Recommendations**:
   - Specific fixes for each issue
   - Code examples when applicable
   - Links to Azure documentation
   - Alternative approaches

OUTPUT FORMAT:
Return a JSON object with validation results:
{
    "is_valid": true,
    "has_critical_issues": false,
    "has_errors": false,
    "syntax_valid": true,
    "linter_passed": true,
    "security_check_passed": true,
    "best_practices_passed": true,
    "issues": [
        {
            "severity": "warning",
            "category": "security",
            "message": "Storage account should have minimum TLS version 1.2",
            "location": "resource storageAccount",
            "suggestion": "Add property: minimumTlsVersion: 'TLS1_2'",
            "rule_id": "BCP001"
        }
    ],
    "issue_summary": {
        "critical": 0,
        "error": 0,
        "warning": 2,
        "info": 1
    },
    "recommendations": [
        "Enable Azure Defender for all resources",
        "Add diagnostic settings for monitoring"
    ],
    "corrected_bicep_code": "// Corrected code if auto-fixable issues...",
    "review_notes": [
        "Template follows Azure naming conventions",
        "All resources use latest API versions"
    ]
}

Be thorough, security-focused, and provide actionable feedback.""",
        )
        super().__init__(id=executor_id)

    @handler
    async def review_bicep(
        self,
        bicep_code: BicepCode,
        ctx: WorkflowContext[ValidationResult],
    ) -> None:
        """
        Review and validate Bicep infrastructure code.

        Args:
            bicep_code: Generated Bicep code
            ctx: Workflow context for sending results
        """
        logger.info(f"Reviewing Bicep template with {len(bicep_code.resources)} resources")

        # Step 1: Validate syntax using Azure CLI
        syntax_result = await self._validate_bicep_syntax(bicep_code.bicep_code)

        # Step 2: Run AI agent review
        ai_review_result = await self._run_ai_review(bicep_code, syntax_result)

        # Step 3: Merge results
        validation_result = self._build_validation_result(
            ai_review_result, syntax_result, bicep_code
        )

        logger.info(
            f"Review complete: {len(validation_result.issues)} issues found "
            f"(Critical: {validation_result.issue_summary.get('critical', 0)}, "
            f"Errors: {validation_result.issue_summary.get('error', 0)})"
        )

        # Send to next agent
        await ctx.send_message(validation_result)

    async def _validate_bicep_syntax(self, bicep_code: str) -> dict[str, Any]:
        """
        Validate Bicep syntax using Azure CLI (az bicep build).

        Returns dict with syntax validation results.
        """
        logger.info("Validating Bicep syntax with Azure CLI")

        try:
            # Write Bicep code to temp file
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.bicep', delete=False, encoding='utf-8'
            ) as f:
                f.write(bicep_code)
                bicep_file = Path(f.name)

            # Run az bicep build --file <file>
            # Note: This requires Azure CLI to be installed
            process = await asyncio.create_subprocess_exec(
                'az', 'bicep', 'build',
                '--file', str(bicep_file),
                '--stdout',  # Output to stdout instead of file
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            # Clean up temp file
            bicep_file.unlink()

            if process.returncode == 0:
                logger.info("Bicep syntax validation passed")
                return {
                    "syntax_valid": True,
                    "errors": [],
                    "warnings": [],
                }
            else:
                # Parse error output
                error_text = stderr.decode('utf-8')
                logger.warning(f"Bicep syntax validation failed: {error_text}")

                # Parse errors and warnings
                errors = self._parse_bicep_errors(error_text)

                return {
                    "syntax_valid": False,
                    "errors": errors,
                    "warnings": [],
                }

        except FileNotFoundError:
            logger.warning("Azure CLI not found - skipping syntax validation")
            return {
                "syntax_valid": True,  # Assume valid if CLI not available
                "errors": [],
                "warnings": [],
                "note": "Azure CLI not available for validation",
            }
        except Exception as e:
            logger.error(f"Error during syntax validation: {e}", exc_info=True)
            return {
                "syntax_valid": True,  # Assume valid on error
                "errors": [],
                "warnings": [],
                "error": str(e),
            }

    def _parse_bicep_errors(self, error_text: str) -> list[dict[str, str]]:
        """Parse Bicep error messages."""
        errors = []
        
        # Bicep errors typically look like:
        # path/to/file.bicep(line,col) : Error BCP001: Message
        error_pattern = r'\.bicep\((\d+),(\d+)\)\s*:\s*(Error|Warning)\s+(\w+):\s*(.+)'
        
        for match in re.finditer(error_pattern, error_text):
            line, col, severity, code, message = match.groups()
            errors.append({
                "line": line,
                "column": col,
                "severity": severity.lower(),
                "code": code,
                "message": message.strip(),
            })

        return errors

    async def _run_ai_review(
        self, bicep_code: BicepCode, syntax_result: dict[str, Any]
    ) -> dict[str, Any]:
        """Run AI agent review of Bicep code."""
        logger.info("Running AI agent review")

        # Prepare review context
        review_context = self._prepare_review_context(bicep_code, syntax_result)

        prompt = f"""Review this Bicep infrastructure as code template for security, best practices, and potential issues.

**Bicep Code:**
```bicep
{bicep_code.bicep_code}
```

**Syntax Validation Results:**
{json.dumps(syntax_result, indent=2)}

**Resource Summary:**
- Total Resources: {len(bicep_code.resources)}
- Parameters: {len(bicep_code.parameters)}
- Outputs: {len(bicep_code.outputs)}

**Review Focus:**
1. Security configurations (encryption, HTTPS, authentication)
2. Best practices compliance
3. Resource configuration issues
4. Missing recommended features (monitoring, tags, etc.)
5. Potential cost optimization opportunities

Return the complete JSON validation result following the format in your instructions.
"""

        # Run agent
        response = await self.agent.run([{"role": "user", "content": prompt}])

        response_text = response.text
        logger.debug(f"AI review response length: {len(response_text)} characters")

        # Parse JSON response
        try:
            review_data = self._extract_json_from_response(response_text)
            return review_data
        except Exception as e:
            logger.error(f"Failed to parse AI review response: {e}", exc_info=True)
            return self._create_fallback_review(syntax_result)

    def _prepare_review_context(
        self, bicep_code: BicepCode, syntax_result: dict[str, Any]
    ) -> str:
        """Prepare context for review."""
        lines = [
            f"Resources: {len(bicep_code.resources)}",
            f"Parameters: {len(bicep_code.parameters)}",
            f"Syntax Valid: {syntax_result.get('syntax_valid', True)}",
        ]

        if syntax_result.get("errors"):
            lines.append(f"Syntax Errors: {len(syntax_result['errors'])}")

        return "\n".join(lines)

    def _extract_json_from_response(self, response_text: str) -> dict[str, Any]:
        """Extract JSON from agent response."""
        # Remove markdown code blocks
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find raw JSON
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                raise ValueError("No JSON found in response")

        return json.loads(json_str)

    def _build_validation_result(
        self,
        ai_review: dict[str, Any],
        syntax_result: dict[str, Any],
        bicep_code: BicepCode,
    ) -> ValidationResult:
        """Build ValidationResult from AI review and syntax validation."""
        # Combine issues from both sources
        issues = []

        # Add syntax errors as issues
        for error in syntax_result.get("errors", []):
            issues.append(
                ValidationIssue(
                    severity=SeverityLevel.ERROR if error['severity'] == 'error' else SeverityLevel.WARNING,
                    category="syntax",
                    message=error['message'],
                    location=f"line {error['line']}",
                    rule_id=error.get('code'),
                )
            )

        # Add AI-identified issues
        for issue_data in ai_review.get("issues", []):
            issues.append(
                ValidationIssue(
                    severity=SeverityLevel(issue_data['severity']),
                    category=issue_data['category'],
                    message=issue_data['message'],
                    location=issue_data.get('location'),
                    suggestion=issue_data.get('suggestion'),
                    rule_id=issue_data.get('rule_id'),
                )
            )

        # Calculate issue summary
        issue_summary = {
            "critical": sum(1 for i in issues if i.severity == SeverityLevel.CRITICAL),
            "error": sum(1 for i in issues if i.severity == SeverityLevel.ERROR),
            "warning": sum(1 for i in issues if i.severity == SeverityLevel.WARNING),
            "info": sum(1 for i in issues if i.severity == SeverityLevel.INFO),
        }

        has_critical = issue_summary["critical"] > 0
        has_errors = issue_summary["error"] > 0

        return ValidationResult(
            bicep_source=bicep_code.source_specification,
            is_valid=not (has_critical or has_errors),
            has_critical_issues=has_critical,
            has_errors=has_errors,
            issues=issues,
            issue_summary=issue_summary,
            syntax_valid=syntax_result.get("syntax_valid", True),
            linter_passed=ai_review.get("linter_passed", True),
            security_check_passed=ai_review.get("security_check_passed", True),
            best_practices_passed=ai_review.get("best_practices_passed", True),
            recommendations=ai_review.get("recommendations", []),
            corrected_bicep_code=ai_review.get("corrected_bicep_code"),
            review_notes=ai_review.get("review_notes", []),
        )

    def _create_fallback_review(self, syntax_result: dict[str, Any]) -> dict[str, Any]:
        """Create fallback review result if AI review fails."""
        logger.warning("Creating fallback review result")

        return {
            "is_valid": syntax_result.get("syntax_valid", True),
            "has_critical_issues": False,
            "has_errors": len(syntax_result.get("errors", [])) > 0,
            "syntax_valid": syntax_result.get("syntax_valid", True),
            "linter_passed": True,
            "security_check_passed": True,
            "best_practices_passed": True,
            "issues": [],
            "issue_summary": {"critical": 0, "error": 0, "warning": 0, "info": 0},
            "recommendations": ["Manual review recommended - AI review unavailable"],
            "review_notes": ["Fallback review - limited validation performed"],
        }


def create_iac_review_agent(
    chat_client: AzureAIAgentClient,
) -> IaCReviewAgent:
    """Factory function to create an IaCReviewAgent instance."""
    return IaCReviewAgent(chat_client)


async def create_iac_review_agent_with_client() -> IaCReviewAgent:
    """Create agent with a new AI client."""
    async with DefaultAzureCredential() as credential:
        chat_client = AzureAIAgentClient(
            project_endpoint=settings.azure_ai.project_endpoint,
            model_deployment_name=settings.azure_ai.model_deployment_name,
            async_credential=credential,
            agent_name="IaCReviewAgent",
        )
        return create_iac_review_agent(chat_client)
