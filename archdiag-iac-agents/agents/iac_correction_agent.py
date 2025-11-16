"""
IaC Correction Agent

This agent takes the ValidationResult from the IaC Review Agent and automatically
corrects issues in the Bicep code. It handles:
- Syntax errors
- Security misconfigurations
- Best practice violations
- Missing required properties

The agent uses AI to intelligently fix issues while preserving the intent of the
original infrastructure design.
"""

import json
import logging
from typing import Any

from agent_framework import Executor, handler
from azure.ai.projects.aio import AIProjectClient

from models.workflow_models import (
    ValidationResult,
    BicepCode,
    SeverityLevel,
    ValidationIssue,
)

logger = logging.getLogger(__name__)


# ================================
# Correction Result Model
# ================================


class CorrectedBicepCode(BicepCode):
    """Extended Bicep code model with correction metadata."""
    
    corrections_applied: list[dict[str, Any]] = []
    original_issues_count: int = 0
    remaining_issues_count: int = 0
    correction_notes: list[str] = []
    auto_fix_success: bool = True


# ================================
# IaC Correction Agent
# ================================


class IaCCorrectionAgent(Executor):
    """
    Agent that automatically corrects issues found in Bicep code validation.
    
    Takes ValidationResult and original BicepCode, applies fixes for identified
    issues, and returns corrected BicepCode ready for deployment.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the IaC Correction Agent."""
        super().__init__(*args, **kwargs)
        logger.info("IaC Correction Agent initialized")

    @handler
    async def correct_bicep_code(
        self,
        validation_result: ValidationResult,
        ctx: Any,
    ) -> CorrectedBicepCode:
        """
        Main handler: Apply corrections to Bicep code based on validation issues.
        
        Args:
            validation_result: Validation result with issues to fix
            ctx: Workflow context containing original Bicep code
            
        Returns:
            CorrectedBicepCode with fixes applied
        """
        logger.info("Starting Bicep code correction process")
        
        try:
            # Get original Bicep code from context
            original_bicep = self._get_bicep_from_context(ctx)
            
            if not original_bicep:
                logger.error("No Bicep code found in context")
                return self._create_error_result(
                    validation_result,
                    "No original Bicep code available for correction"
                )
            
            # Check if correction is needed
            if validation_result.is_valid and not validation_result.issues:
                logger.info("Code is valid, no corrections needed")
                return self._create_no_correction_result(original_bicep, validation_result)
            
            # Categorize issues by severity and type
            issues_by_severity = self._categorize_issues(validation_result.issues)
            
            logger.info(
                f"Found {len(validation_result.issues)} issues: "
                f"Critical={len(issues_by_severity['critical'])}, "
                f"Error={len(issues_by_severity['error'])}, "
                f"Warning={len(issues_by_severity['warning'])}, "
                f"Info={len(issues_by_severity['info'])}"
            )
            
            # Prepare correction request for AI
            correction_prompt = self._prepare_correction_prompt(
                original_bicep,
                validation_result,
                issues_by_severity,
            )
            
            # Call AI to generate corrected code
            logger.info("Requesting AI to correct Bicep code")
            corrected_code = await self._apply_ai_corrections(correction_prompt)
            
            # Build result
            result = self._build_corrected_result(
                original_bicep,
                corrected_code,
                validation_result,
                issues_by_severity,
            )
            
            logger.info(
                f"Correction completed: {result.corrections_applied} fixes applied, "
                f"{result.remaining_issues_count} issues remaining"
            )
            
            return result
            
        except Exception as e:
            logger.exception("Error during Bicep correction")
            return self._create_error_result(
                validation_result,
                f"Correction failed: {str(e)}"
            )

    def _get_bicep_from_context(self, ctx: Any) -> BicepCode | None:
        """Extract original Bicep code from workflow context."""
        try:
            if hasattr(ctx, "bicep_code"):
                return ctx.bicep_code
            
            # Try to get from previous stage output
            if hasattr(ctx, "get_stage_output"):
                return ctx.get_stage_output("iac_generation")
            
            logger.warning("Could not find Bicep code in context")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting Bicep from context: {e}")
            return None

    def _categorize_issues(
        self,
        issues: list[ValidationIssue],
    ) -> dict[str, list[ValidationIssue]]:
        """Categorize issues by severity level."""
        categorized = {
            "critical": [],
            "error": [],
            "warning": [],
            "info": [],
        }
        
        for issue in issues:
            severity_key = issue.severity.value
            if severity_key in categorized:
                categorized[severity_key].append(issue)
        
        return categorized

    def _prepare_correction_prompt(
        self,
        original_bicep: BicepCode,
        validation_result: ValidationResult,
        issues_by_severity: dict[str, list[ValidationIssue]],
    ) -> str:
        """Prepare detailed prompt for AI to correct Bicep code."""
        
        # Build issues summary
        issues_text = []
        for severity in ["critical", "error", "warning", "info"]:
            issues = issues_by_severity[severity]
            if issues:
                issues_text.append(f"\n{severity.upper()} Issues ({len(issues)}):")
                for idx, issue in enumerate(issues, 1):
                    issues_text.append(
                        f"{idx}. [{issue.category}] {issue.message}"
                    )
                    if issue.location:
                        issues_text.append(f"   Location: {issue.location}")
                    if issue.suggestion:
                        issues_text.append(f"   Suggested Fix: {issue.suggestion}")
        
        issues_summary = "\n".join(issues_text)
        
        prompt = f"""You are an expert Azure Bicep code correction specialist. Your task is to fix issues in the provided Bicep code while preserving the original infrastructure design intent.

ORIGINAL BICEP CODE:
```bicep
{original_bicep.bicep_code}
```

VALIDATION ISSUES TO FIX:
{issues_summary}

VALIDATION SUMMARY:
- Syntax Valid: {validation_result.syntax_valid}
- Security Check Passed: {validation_result.security_check_passed}
- Best Practices Passed: {validation_result.best_practices_passed}

CORRECTION REQUIREMENTS:

1. **Critical and Error Issues** (MUST FIX):
   - Fix all syntax errors to ensure code compiles
   - Correct security misconfigurations (encryption, authentication, network security)
   - Add missing required properties
   - Fix API version issues

2. **Warning Issues** (SHOULD FIX):
   - Apply Azure best practices
   - Add recommended security features (managed identity, HTTPS, etc.)
   - Improve naming conventions
   - Add missing tags where appropriate

3. **Info Issues** (OPTIONAL):
   - Consider suggestions for optimization
   - Add helpful comments
   - Improve code structure

4. **Preservation Requirements**:
   - Maintain all resource definitions from original code
   - Keep the same resource types and structure
   - Preserve parameter names and outputs
   - Keep deployment scope and target

5. **Code Quality**:
   - Use latest stable API versions
   - Follow Azure naming conventions
   - Add descriptive comments for fixes
   - Ensure proper dependency ordering
   - Use symbolic names consistently

RESPONSE FORMAT:
Provide the complete corrected Bicep code. Include ALL resources, parameters, variables, and outputs.
Add comments (// FIXED:) before corrected lines to indicate what was changed.

Return ONLY valid Bicep code, no explanations outside the code."""

        return prompt

    async def _apply_ai_corrections(self, prompt: str) -> str:
        """Use AI to generate corrected Bicep code."""
        try:
            # Get the agent's chat completion capability
            response = await self.chat(prompt)
            
            # Extract corrected code from response
            corrected_code = self._extract_bicep_from_response(response)
            
            return corrected_code
            
        except Exception as e:
            logger.error(f"AI correction failed: {e}")
            raise

    def _extract_bicep_from_response(self, response: str) -> str:
        """Extract Bicep code from AI response."""
        # Remove markdown code blocks if present
        if "```bicep" in response:
            start = response.find("```bicep") + len("```bicep")
            end = response.find("```", start)
            if end != -1:
                return response[start:end].strip()
        elif "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            if end != -1:
                return response[start:end].strip()
        
        # Return as-is if no code blocks found
        return response.strip()

    def _build_corrected_result(
        self,
        original_bicep: BicepCode,
        corrected_code: str,
        validation_result: ValidationResult,
        issues_by_severity: dict[str, list[ValidationIssue]],
    ) -> CorrectedBicepCode:
        """Build the corrected Bicep code result."""
        
        # Count corrections by analyzing FIXED comments
        corrections = []
        correction_lines = [
            line for line in corrected_code.split("\n") 
            if "// FIXED:" in line or "// CORRECTED:" in line
        ]
        
        for line in correction_lines:
            corrections.append({
                "description": line.strip(),
                "type": "auto_fix",
            })
        
        # Build correction notes
        notes = []
        original_issue_count = len(validation_result.issues)
        
        if issues_by_severity["critical"]:
            notes.append(
                f"Fixed {len(issues_by_severity['critical'])} critical issues"
            )
        if issues_by_severity["error"]:
            notes.append(
                f"Fixed {len(issues_by_severity['error'])} error issues"
            )
        if issues_by_severity["warning"]:
            notes.append(
                f"Applied {len(issues_by_severity['warning'])} warning fixes"
            )
        
        notes.append(f"Total corrections: {len(corrections)}")
        
        # Create result
        result = CorrectedBicepCode(
            generated_at=original_bicep.generated_at,
            source_specification=original_bicep.source_specification,
            parameters=original_bicep.parameters,
            variables=original_bicep.variables,
            resources=original_bicep.resources,
            outputs=original_bicep.outputs,
            bicep_code=corrected_code,
            target_scope=original_bicep.target_scope,
            version="1.1",  # Incremented version
            generation_notes=original_bicep.generation_notes + [
                "Code corrected by IaC Correction Agent"
            ],
            corrections_applied=corrections,
            original_issues_count=original_issue_count,
            remaining_issues_count=0,  # Assume all fixed, re-validation will confirm
            correction_notes=notes,
            auto_fix_success=True,
        )
        
        return result

    def _create_no_correction_result(
        self,
        original_bicep: BicepCode,
        validation_result: ValidationResult,
    ) -> CorrectedBicepCode:
        """Create result when no corrections are needed."""
        return CorrectedBicepCode(
            generated_at=original_bicep.generated_at,
            source_specification=original_bicep.source_specification,
            parameters=original_bicep.parameters,
            variables=original_bicep.variables,
            resources=original_bicep.resources,
            outputs=original_bicep.outputs,
            bicep_code=original_bicep.bicep_code,
            target_scope=original_bicep.target_scope,
            version=original_bicep.version,
            generation_notes=original_bicep.generation_notes + [
                "No corrections needed - code passed validation"
            ],
            corrections_applied=[],
            original_issues_count=0,
            remaining_issues_count=0,
            correction_notes=["Code is valid, no corrections applied"],
            auto_fix_success=True,
        )

    def _create_error_result(
        self,
        validation_result: ValidationResult,
        error_message: str,
    ) -> CorrectedBicepCode:
        """Create error result when correction fails."""
        from datetime import datetime
        
        return CorrectedBicepCode(
            generated_at=datetime.utcnow(),
            source_specification="error",
            parameters=[],
            variables=[],
            resources=[],
            outputs=[],
            bicep_code="// Correction failed - see error message",
            target_scope="resourceGroup",
            version="error",
            generation_notes=[f"ERROR: {error_message}"],
            corrections_applied=[],
            original_issues_count=len(validation_result.issues),
            remaining_issues_count=len(validation_result.issues),
            correction_notes=[error_message],
            auto_fix_success=False,
        )


# ================================
# Factory Function
# ================================


def create_iac_correction_agent(chat_client: AIProjectClient) -> IaCCorrectionAgent:
    """
    Create and configure the IaC Correction Agent.
    
    Args:
        chat_client: Azure AI Project client for chat completions
        
    Returns:
        Configured IaC Correction Agent instance
    """
    logger.info("Creating IaC Correction Agent")
    
    # Create agent with comprehensive instructions
    instructions = """You are an expert Azure Bicep code correction specialist.

Your role is to automatically fix issues in Bicep infrastructure code while preserving
the original design intent. You excel at:

1. **Syntax Correction**:
   - Fix compilation errors
   - Correct malformed expressions
   - Ensure proper Bicep syntax

2. **Security Enhancement**:
   - Enable encryption at rest and in transit
   - Configure managed identities
   - Enforce HTTPS/TLS
   - Apply network security rules
   - Configure Key Vault integration

3. **Best Practices Application**:
   - Use latest stable API versions
   - Follow Azure naming conventions
   - Add proper tags
   - Configure diagnostics and monitoring
   - Ensure high availability settings

4. **Property Completion**:
   - Add missing required properties
   - Set secure defaults
   - Configure dependencies correctly

Always provide complete, deployable Bicep code with clear comments indicating fixes."""

    agent = IaCCorrectionAgent(
        client=chat_client,
        model="gpt-4o",  # Use same model as other agents
        instructions=instructions,
        name="iac-correction-agent",
    )
    
    logger.info("IaC Correction Agent created successfully")
    return agent
