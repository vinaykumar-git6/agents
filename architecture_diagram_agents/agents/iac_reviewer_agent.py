"""
IAC Reviewer Agent using Microsoft Agent Framework with Azure AI Foundry.
Reviews Terraform code for syntax, best practices, and security.
Includes terraform validate capability to verify code correctness.
"""

import os
import json
import asyncio
import subprocess
import shutil
import tempfile
from typing import Optional, Dict, Any

from azure.identity.aio import AzureCliCredential
from azure.ai.projects.aio import AIProjectClient
from azure.ai.agents.aio import AgentsClient
from agent_framework import ChatAgent
from agent_framework.azure import AzureAIAgentClient
from dotenv import load_dotenv

from ..core.config import Config
from ..utils.legacy_utils import setup_logger

# Load .env from project root
env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=env_path, override=True)

logger = setup_logger(__name__)

# Configuration
project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
model_deployment_name = os.environ.get("AZURE_AI_REVIEWER_MODEL", "gpt-4.1")


def validate_terraform(terraform_code_json: str) -> str:
    """
    Validate Terraform code by running terraform init and validate commands.
    
    This tool saves the provided Terraform files to a temporary directory,
    runs 'terraform init -backend=false' followed by 'terraform validate',
    and returns the validation results including any errors or warnings.
    
    Args:
        terraform_code_json: JSON string containing terraform file contents with keys:
                            providers_tf, main_tf, variables_tf, outputs_tf, terraform_tfvars
    
    Returns:
        JSON string with validation results including:
        - valid: boolean indicating if code passed validation
        - errors: list of error messages with file and line info
        - warnings: list of warning messages
        - summary: human-readable summary of validation status
    """
    try:
        terraform_files = json.loads(terraform_code_json)
    except json.JSONDecodeError as e:
        return json.dumps({
            "valid": False,
            "errors": [{"message": f"Invalid JSON input: {e}"}],
            "warnings": [],
            "summary": "Failed to parse terraform code JSON"
        })
    
    # Check if terraform CLI is available
    terraform_exe = shutil.which("terraform")
    if not terraform_exe:
        # Try common Windows paths
        possible_paths = [
            r"C:\Users\vinaykumar\OneDrive - Microsoft\Documents\Softwares\terraform_1.14.3_windows_amd64\terraform.exe",
            r"C:\Program Files\Terraform\terraform.exe",
        ]
        for path in possible_paths:
            if os.path.exists(path):
                terraform_exe = path
                break
    
    if not terraform_exe:
        return json.dumps({
            "valid": False,
            "errors": [{"message": "Terraform CLI not found in PATH"}],
            "warnings": [],
            "summary": "Cannot validate - Terraform CLI not installed"
        })
    
    # Create temporary directory for terraform files
    temp_dir = tempfile.mkdtemp(prefix="tf_validate_")
    
    try:
        # Write terraform files to temp directory
        file_mapping = {
            'providers_tf': 'providers.tf',
            'main_tf': 'main.tf',
            'variables_tf': 'variables.tf',
            'outputs_tf': 'outputs.tf',
            'terraform_tfvars': 'terraform.tfvars',
        }
        
        files_written = []
        for key, filename in file_mapping.items():
            content = terraform_files.get(key, '')
            if content and len(content.strip()) > 0:
                file_path = os.path.join(temp_dir, filename)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                files_written.append(filename)
        
        if not files_written:
            return json.dumps({
                "valid": False,
                "errors": [{"message": "No terraform files provided"}],
                "warnings": [],
                "summary": "No terraform files to validate"
            })
        
        logger.info(f"[TerraformValidate] Validating files: {files_written} in {temp_dir}")
        
        result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "init_output": "",
            "validate_output": "",
            "summary": ""
        }
        
        # Step 1: terraform init -backend=false
        logger.info("[TerraformValidate] Running terraform init -backend=false")
        init_result = subprocess.run(
            [terraform_exe, "init", "-backend=false", "-input=false", "-no-color"],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        result["init_output"] = init_result.stdout + init_result.stderr
        
        if init_result.returncode != 0:
            # Parse init errors
            error_output = init_result.stderr or init_result.stdout
            result["valid"] = False
            result["errors"].append({
                "phase": "init",
                "message": error_output,
                "suggestion": "Check provider configuration and required_providers block"
            })
            result["summary"] = f"Terraform init failed: {error_output[:500]}"
            logger.error(f"[TerraformValidate] init failed: {error_output}")
            return json.dumps(result)
        
        logger.info("[TerraformValidate] init successful")
        
        # Step 2: terraform validate -json
        logger.info("[TerraformValidate] Running terraform validate -json")
        validate_result = subprocess.run(
            [terraform_exe, "validate", "-json", "-no-color"],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        result["validate_output"] = validate_result.stdout
        
        # Parse JSON validation output
        try:
            validate_json = json.loads(validate_result.stdout)
            result["valid"] = validate_json.get("valid", False)
            
            # Extract diagnostics (errors and warnings)
            for diag in validate_json.get("diagnostics", []):
                diag_info = {
                    "severity": diag.get("severity", "error"),
                    "summary": diag.get("summary", "Unknown error"),
                    "detail": diag.get("detail", ""),
                }
                
                # Add file/line info if available
                if "range" in diag:
                    range_info = diag["range"]
                    diag_info["file"] = range_info.get("filename", "")
                    if "start" in range_info:
                        diag_info["line"] = range_info["start"].get("line", 0)
                        diag_info["column"] = range_info["start"].get("column", 0)
                
                if diag.get("severity") == "error":
                    result["errors"].append(diag_info)
                else:
                    result["warnings"].append(diag_info)
            
            # Build summary
            error_count = len(result["errors"])
            warning_count = len(result["warnings"])
            
            if result["valid"]:
                result["summary"] = f"✓ Terraform validation PASSED. {warning_count} warning(s)."
            else:
                result["summary"] = f"✗ Terraform validation FAILED. {error_count} error(s), {warning_count} warning(s)."
                
                # Add specific error details to summary
                if result["errors"]:
                    error_details = []
                    for err in result["errors"][:5]:  # Limit to first 5 errors
                        loc = ""
                        if "file" in err and "line" in err:
                            loc = f" ({err['file']}:{err['line']})"
                        error_details.append(f"- {err['summary']}{loc}")
                    result["summary"] += "\n\nErrors:\n" + "\n".join(error_details)
            
            logger.info(f"[TerraformValidate] {result['summary']}")
            
        except json.JSONDecodeError:
            # Fallback to text parsing if JSON fails
            result["valid"] = validate_result.returncode == 0
            if not result["valid"]:
                result["errors"].append({
                    "message": validate_result.stderr or validate_result.stdout,
                    "phase": "validate"
                })
                result["summary"] = f"Validation failed: {validate_result.stderr or validate_result.stdout}"
            else:
                result["summary"] = "Terraform validation passed"
        
        return json.dumps(result)
        
    except subprocess.TimeoutExpired:
        return json.dumps({
            "valid": False,
            "errors": [{"message": "Terraform command timed out"}],
            "warnings": [],
            "summary": "Validation timed out"
        })
    except Exception as e:
        logger.error(f"[TerraformValidate] Error: {e}", exc_info=True)
        return json.dumps({
            "valid": False,
            "errors": [{"message": str(e)}],
            "warnings": [],
            "summary": f"Validation error: {e}"
        })
    finally:
        # Cleanup temp directory
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


class IACReviewerAgent:
    """Agent that reviews Terraform code for syntax, best practices, and security with validation capability."""
    
    # Instructions for the reviewer agent
    REVIEWER_INSTRUCTIONS = """You are an expert Terraform code reviewer for Azure infrastructure with validation capability.

**IMPORTANT: You have access to a validate_terraform tool. You MUST use it to validate the terraform code!**

**Step 1: ALWAYS Run Terraform Validation First**
When you receive terraform code, call the validate_terraform tool with the terraform code to check for syntax errors.
Pass the terraform code as a JSON string with keys: providers_tf, main_tf, variables_tf, outputs_tf, terraform_tfvars

Example tool call format:
{"providers_tf": "...", "main_tf": "...", "variables_tf": "...", "outputs_tf": "...", "terraform_tfvars": "..."}

**Step 2: Code Review Checklist - Score each category (0-100):**

1. **File Completeness (25 points):**
   - All required files present: providers.tf, main.tf, variables.tf, outputs.tf, terraform.tfvars, README.md
   - README.md has deployment instructions, prerequisites, and usage guide
   - No missing critical files

2. **Code Documentation (25 points):**
   - EVERY resource in main.tf has explanatory comments
   - Variables have clear descriptions
   - Outputs have descriptions
   - README.md is comprehensive and helpful
   - Comments explain WHY, not just WHAT

3. **Best Practices (25 points):**
   - Azure naming conventions followed (rg-, app-, kv-, etc.)
   - All values are variables (no hardcoded values)
   - Proper resource tags (Environment, ManagedBy, etc.)
   - Variable validation rules where appropriate
   - Correct Azure provider version constraints

4. **Security & Quality (25 points):**
   - No hardcoded secrets or sensitive data
   - Managed identities or Key Vault references used
   - Proper resource dependencies
   - Error-free Terraform syntax (use validate_terraform tool!)
   - Following Azure security best practices

**Return JSON with this EXACT structure:**
{
  "terraform_validation": {
    "ran_validation": true/false,
    "valid": true/false,
    "errors": ["list of validation errors if any"],
    "warnings": ["list of warnings if any"]
  },
  "overall_score": 0-100,
  "category_scores": {
    "file_completeness": 0-25,
    "code_documentation": 0-25,
    "best_practices": 0-25,
    "security_quality": 0-25
  },
  "passed": true/false (true only if overall_score >= 85 AND terraform_validation.valid is true),
  "issues": [
    {
      "file": "filename",
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "category": "validation|completeness|documentation|best_practices|security",
      "issue": "specific problem",
      "suggestion": "how to fix it",
      "line": optional_line_number
    }
  ],
  "summary": "1-2 sentence overall assessment",
  "refinement_priority": ["fix this first", "then this", "finally this"]
}

**Severity Guidelines:**
- CRITICAL: Terraform validation error, missing required file, syntax error, security vulnerability, hardcoded secret
- HIGH: Missing comments on resources, no README deployment steps, hardcoded values
- MEDIUM: Inconsistent naming, missing tags, incomplete variable descriptions
- LOW: Terraform warnings, minor formatting issues, optional improvements

**IMPORTANT RULES:**
1. ALWAYS call validate_terraform first before doing manual review
2. If validation fails, mark as NOT passed regardless of other scores
3. Include ALL validation errors in the issues list with "validation" category
4. Be STRICT: Only pass (score >= 85 AND valid) if code is truly production-ready with complete documentation."""
    
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config.from_environment()
        self.project_endpoint = project_endpoint
        self.model_deployment_name = model_deployment_name
        self.agent: Optional[ChatAgent] = None
        self._agents_client = None
        self._credential = None
        self._created_agent = None
        self._initialized = False
        logger.info("IACReviewerAgent instantiated")
    
    async def initialize(self) -> None:
        """Initialize Azure AI agent for code review with terraform validate tool."""
        if self._initialized:
            return
        
        try:
            self._credential = AzureCliCredential()
            
            # Use AgentsClient (has create_agent method)
            self._agents_client = AgentsClient(
                endpoint=self.project_endpoint,
                credential=self._credential
            )
            await self._agents_client.__aenter__()
            
            logger.info(f"Initializing IACReviewerAgent with model: {self.model_deployment_name}")
            
            # Create base agent via AgentsClient
            self._created_agent = await self._agents_client.create_agent(
                model=self.model_deployment_name,
                name="TerraformReviewer",
                instructions=self.REVIEWER_INSTRUCTIONS
            )
            
            logger.info(f"Created reviewer agent with ID: {self._created_agent.id}")
            
            # Wrap agent with ChatAgent and tools
            self.agent = ChatAgent(
                chat_client=AzureAIAgentClient(
                    agents_client=self._agents_client,
                    agent_id=self._created_agent.id
                ),
                tools=[
                    validate_terraform,  # Pass function directly - framework generates schema
                ],
                store=True
            )
            
            self._initialized = True
            logger.info("IACReviewerAgent initialized with validate_terraform tool")
            
        except Exception as e:
            logger.error(f"Failed to initialize IACReviewerAgent: {e}")
            raise
    
    async def review(self, terraform_code: Dict[str, str], requirements: str = "") -> Dict[str, Any]:
        """
        Review Terraform code using the agent with validation tool.
        
        Args:
            terraform_code: Dictionary with terraform file contents
            requirements: Original architecture requirements for context
            
        Returns:
            Review results with validation status and recommendations
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            # Prepare the review request - use the already initialized agent
            terraform_json = json.dumps(terraform_code)
            
            prompt = f"""Review this Terraform code for Azure infrastructure:

**Original Requirements:**
{requirements}

**Terraform Code Files:**
```json
{terraform_json}
```

**INSTRUCTIONS:**
1. FIRST: Call validate_terraform with the terraform code JSON to check for syntax errors
2. THEN: Perform your code review
3. Return a comprehensive JSON review with validation results included

Remember to pass the terraform code as JSON to the validate_terraform tool with keys:
providers_tf, main_tf, variables_tf, outputs_tf, terraform_tfvars"""

            logger.info("[IACReviewerAgent] Running review with terraform validation...")
            
            # Run the agent
            response = await self.agent.run(prompt)
            
            logger.info(f"[IACReviewerAgent] Review complete")
            
            # Parse the response
            result = {
                "raw_response": response,
                "terraform_validation": {"ran_validation": False, "valid": False},
                "passed": False,
                "issues": []
            }
            
            # Try to extract JSON from response
            if response:
                try:
                    # Find JSON in response
                    json_start = response.find('{')
                    json_end = response.rfind('}') + 1
                    if json_start != -1 and json_end > json_start:
                        json_str = response[json_start:json_end]
                        parsed = json.loads(json_str)
                        result.update(parsed)
                except json.JSONDecodeError:
                    logger.warning("Could not parse JSON from reviewer response")
                    result["issues"].append({
                        "severity": "HIGH",
                        "category": "review",
                        "issue": "Could not parse review response as JSON",
                        "suggestion": "Check response format"
                    })
            
            return result
                
        except Exception as e:
            logger.error(f"Error during review: {e}", exc_info=True)
            return {
                "passed": False,
                "error": str(e),
                "terraform_validation": {"ran_validation": False, "valid": False, "error": str(e)},
                "issues": [{"severity": "CRITICAL", "issue": f"Review failed: {e}"}]
            }
    
    async def close(self) -> None:
        """Close the agent connection and release resources."""
        try:
            # Delete the created agent
            if self._created_agent and self._agents_client:
                try:
                    logger.info(f"Deleting reviewer agent: {self._created_agent.id}")
                    await self._agents_client.delete_agent(self._created_agent.id)
                except Exception as e:
                    logger.warning(f"Error deleting agent: {e}")
                self._created_agent = None
            
            if self._agents_client:
                logger.info("Closing IACReviewerAgent client")
                await self._agents_client.__aexit__(None, None, None)
                self._agents_client = None
            if self._credential:
                await self._credential.close()
                self._credential = None
            self.agent = None
            self._initialized = False
        except Exception as e:
            logger.warning(f"Error closing agent: {e}")


async def main():
    """Test the IAC Reviewer Agent with validation."""
    try:
        agent = IACReviewerAgent()
        
        # Sample terraform code for testing
        test_code = {
            "providers_tf": '''terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
}
''',
            "main_tf": '''# Resource Group
resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location
}
''',
            "variables_tf": '''variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "eastus"
}
''',
            "outputs_tf": '''output "resource_group_id" {
  description = "The ID of the resource group"
  value       = azurerm_resource_group.main.id
}
''',
            "terraform_tfvars": '''resource_group_name = "rg-test-app"
location            = "eastus"
'''
        }
        
        # Run review with validation
        result = await agent.review(test_code, "Simple resource group infrastructure")
        
        logger.info(f"Review Result: {json.dumps(result, indent=2)}")
        
        if result.get("terraform_validation", {}).get("valid"):
            logger.info("✓ Terraform validation passed!")
        else:
            logger.warning("✗ Terraform validation failed")
            
        if result.get("passed"):
            logger.info("✓ Code review passed!")
        else:
            logger.warning("✗ Code review did not pass")
        
    except Exception as e:
        logger.error(f"Failed to run IACReviewerAgent: {e}")
        return None


if __name__ == "__main__":
    asyncio.run(main())
