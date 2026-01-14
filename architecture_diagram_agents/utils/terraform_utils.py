"""
Terraform Utility Functions
Helper functions for Terraform code parsing, saving, and plan generation.
"""

import os
import re
import subprocess
import shutil
from pathlib import Path
from typing import Any, Dict

from .legacy_utils import setup_logger
from .logging_config import setup_logging

# Initialize logging
setup_logging(level="INFO")
logger = setup_logger(__name__)


# ============================================================================
# ANSI Color Constants
# ============================================================================

ANSI_COLORS = {
    'CYAN': '\033[96m',
    'YELLOW': '\033[93m',
    'GREEN': '\033[92m',
    'MAGENTA': '\033[95m',
    'BLUE': '\033[94m',
    'BOLD': '\033[1m',
    'RESET': '\033[0m',
}


# ============================================================================
# Terraform Plan Preparation
# ============================================================================

async def prepare_terraform_plan(terraform_path: str) -> Dict[str, Any]:
    """
    Run terraform init and plan to prepare plan.json for Infracost.
    
    Steps:
    1. terraform init -backend=false (skip remote backend)
    2. terraform plan -out=tfplan.binary -input=false
    3. terraform show -json tfplan.binary > plan.json
    
    Args:
        terraform_path: Path to the terraform project directory
        
    Returns:
        Dict with status, plan_json_path, and any errors
    """
    result = {
        "status": "SUCCESS",
        "plan_json_path": None,
        "terraform_initialized": False,
        "plan_generated": False,
        "errors": []
    }
    
    # Check if terraform is available
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
        result["status"] = "ERROR"
        result["errors"].append("Terraform executable not found in PATH")
        logger.warning("Terraform not found, skipping plan generation")
        return result
    
    logger.info(f"[TerraformPlan] Using terraform: {terraform_exe}")
    logger.info(f"[TerraformPlan] Working directory: {terraform_path}")
    
    # ANSI colors for output
    CYAN = ANSI_COLORS['CYAN']
    GREEN = ANSI_COLORS['GREEN']
    YELLOW = ANSI_COLORS['YELLOW']
    RESET = ANSI_COLORS['RESET']
    BOLD = ANSI_COLORS['BOLD']
    
    print(f"\n{BOLD}{'=' * 80}{RESET}")
    print(f"{CYAN}{BOLD}[TERRAFORM]{RESET} {CYAN}Preparing Terraform Plan{RESET}")
    print(f"{BOLD}{'-' * 80}{RESET}")
    
    try:
        # Step 1: terraform init -backend=false
        print(f"{YELLOW}[1/3] Running terraform init -backend=false...{RESET}")
        logger.info("[TerraformPlan] Running terraform init -backend=false")
        
        init_result = subprocess.run(
            [terraform_exe, "init", "-backend=false", "-input=false", "-no-color"],
            cwd=terraform_path,
            capture_output=True,
            text=True,
            timeout=300  # 5 min timeout
        )
        
        if init_result.returncode != 0:
            error_msg = init_result.stderr or init_result.stdout
            result["errors"].append(f"terraform init failed: {error_msg}")
            logger.error(f"[TerraformPlan] init failed: {error_msg}")
            print(f"{YELLOW}  ⚠️ Init failed: {error_msg[:200]}{RESET}")
        else:
            result["terraform_initialized"] = True
            print(f"{GREEN}  ✓ Terraform initialized{RESET}")
            logger.info("[TerraformPlan] init successful")
        
        # Step 2: terraform plan -out=tfplan.binary
        if result["terraform_initialized"]:
            print(f"{YELLOW}[2/3] Running terraform plan...{RESET}")
            logger.info("[TerraformPlan] Running terraform plan -out=tfplan.binary")
            
            plan_result = subprocess.run(
                [terraform_exe, "plan", "-out=tfplan.binary", "-input=false", "-no-color"],
                cwd=terraform_path,
                capture_output=True,
                text=True,
                timeout=600  # 10 min timeout
            )
            
            if plan_result.returncode != 0:
                error_msg = plan_result.stderr or plan_result.stdout
                result["errors"].append(f"terraform plan failed: {error_msg}")
                logger.error(f"[TerraformPlan] plan failed: {error_msg}")
                print(f"{YELLOW}  ⚠️ Plan failed: {error_msg[:200]}{RESET}")
            else:
                result["plan_generated"] = True
                print(f"{GREEN}  ✓ Terraform plan generated{RESET}")
                logger.info("[TerraformPlan] plan successful")
        
        # Step 3: terraform show -json tfplan.binary > plan.json
        if result["plan_generated"]:
            print(f"{YELLOW}[3/3] Converting plan to JSON...{RESET}")
            logger.info("[TerraformPlan] Running terraform show -json tfplan.binary")
            
            show_result = subprocess.run(
                [terraform_exe, "show", "-json", "tfplan.binary"],
                cwd=terraform_path,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if show_result.returncode != 0:
                error_msg = show_result.stderr or show_result.stdout
                result["errors"].append(f"terraform show failed: {error_msg}")
                logger.error(f"[TerraformPlan] show failed: {error_msg}")
                print(f"{YELLOW}  ⚠️ Show failed: {error_msg[:200]}{RESET}")
            else:
                plan_json_path = os.path.join(terraform_path, "plan.json")
                with open(plan_json_path, 'w', encoding='utf-8') as f:
                    f.write(show_result.stdout)
                result["plan_json_path"] = plan_json_path
                print(f"{GREEN}  ✓ Plan JSON saved to: plan.json{RESET}")
                logger.info(f"[TerraformPlan] plan.json saved to: {plan_json_path}")
        
        # Final status
        if result["plan_json_path"]:
            print(f"{GREEN}{BOLD}✓ Terraform plan ready for Infracost{RESET}")
        else:
            result["status"] = "PARTIAL" if result["terraform_initialized"] else "ERROR"
            print(f"{YELLOW}⚠️ Terraform plan incomplete - Infracost will use HCL files directly{RESET}")
        
        print(f"{BOLD}{'=' * 80}{RESET}\n")
        
    except subprocess.TimeoutExpired as e:
        result["status"] = "ERROR"
        result["errors"].append(f"Terraform command timed out: {e}")
        logger.error(f"[TerraformPlan] Timeout: {e}")
        print(f"{YELLOW}⚠️ Terraform command timed out{RESET}")
        
    except Exception as e:
        result["status"] = "ERROR"
        result["errors"].append(f"Terraform preparation failed: {e}")
        logger.error(f"[TerraformPlan] Error: {e}", exc_info=True)
        print(f"{YELLOW}⚠️ Terraform preparation error: {e}{RESET}")
    
    return result


# ============================================================================
# Backend Block Stripping
# ============================================================================

def strip_backend_block(providers_content: str) -> str:
    """
    Remove the backend block from providers.tf content to avoid remote backend
    issues during local validation. The backend block requires actual Azure
    storage configuration which is not available during terraform validate/plan.
    
    Args:
        providers_content: The content of providers.tf file
        
    Returns:
        providers_content with backend block removed
    """
    if not providers_content:
        return providers_content
    
    # Pattern to match backend "azurerm" { ... } block with nested braces
    # This handles multi-line backend blocks with any indentation
    result = []
    lines = providers_content.split('\n')
    in_backend_block = False
    brace_count = 0
    
    for line in lines:
        stripped = line.strip()
        
        # Detect start of backend block
        if not in_backend_block and re.match(r'backend\s+["\']?\w+["\']?\s*\{', stripped):
            in_backend_block = True
            brace_count = stripped.count('{') - stripped.count('}')
            logger.info(f"[strip_backend_block] Removing backend block from providers.tf")
            continue
        
        if in_backend_block:
            brace_count += line.count('{') - line.count('}')
            if brace_count <= 0:
                in_backend_block = False
            continue
        
        result.append(line)
    
    return '\n'.join(result)


# ============================================================================
# Terraform File Saving
# ============================================================================

def save_terraform_project(terraform_data: Dict[str, str], output_dir: str) -> str:
    """
    Save Terraform files to disk.
    
    Args:
        terraform_data: Dict with keys like 'providers_tf', 'main_tf', etc.
        output_dir: Directory path to save files
        
    Returns:
        Path to the created directory
    """
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    
    # Strip backend block from providers.tf to avoid remote backend issues during validation
    providers_content = terraform_data.get('providers_tf', '')
    providers_content = strip_backend_block(providers_content)
    
    files = {
        'providers.tf': providers_content,
        'main.tf': terraform_data.get('main_tf', ''),
        'variables.tf': terraform_data.get('variables_tf', ''),
        'outputs.tf': terraform_data.get('outputs_tf', ''),
        'terraform.tfvars': terraform_data.get('terraform_tfvars', ''),
        'README.md': terraform_data.get('README_md', '')
    }
    
    for filename, content in files.items():
        if content:
            (path / filename).write_text(content, encoding='utf-8')
    
    return str(path)


# ============================================================================
# Terraform Block Extraction
# ============================================================================

def extract_terraform_block(text: str, start_pos: int) -> str:
    """
    Extract a complete Terraform block starting from start_pos.
    Handles nested braces correctly.
    
    Args:
        text: Full text containing terraform code
        start_pos: Position where the block starts
        
    Returns:
        Complete terraform block as string
    """
    # Find the opening brace
    brace_start = text.find('{', start_pos)
    if brace_start == -1:
        return ""
    
    # Count braces to find the matching closing brace
    brace_count = 0
    pos = brace_start
    
    while pos < len(text):
        char = text[pos]
        if char == '{':
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0:
                # Found matching closing brace
                return text[start_pos:pos + 1]
        pos += 1
    
    # If we reach here, braces are unbalanced - return what we have
    return text[start_pos:min(start_pos + 5000, len(text))]


# ============================================================================
# Terraform File Parsing
# ============================================================================

def parse_terraform_files(text: str) -> Dict[str, str]:
    """
    Parse Terraform code text into separate file contents.
    
    Handles various LLM output formats:
    - Code blocks with filename headers: === providers.tf === followed by ```hcl...```
    - Code blocks with filename in language tag: ```hcl:providers.tf or ```terraform:main.tf
    - Markdown headers: ### providers.tf, ## main.tf, # variables.tf
    - Section markers: === providers.tf ===, --- providers.tf ---
    
    Args:
        text: Raw text containing terraform code (typically from LLM output)
        
    Returns:
        Dict with keys: providers_tf, main_tf, variables_tf, outputs_tf, terraform_tfvars, README_md
    """
    terraform_files = {
        'providers_tf': '',
        'main_tf': '',
        'variables_tf': '',
        'outputs_tf': '',
        'terraform_tfvars': '',
        'README_md': ''
    }
    
    file_mapping = {
        'providers.tf': 'providers_tf',
        'provider.tf': 'providers_tf',
        'main.tf': 'main_tf',
        'variables.tf': 'variables_tf',
        'variable.tf': 'variables_tf',
        'vars.tf': 'variables_tf',
        'outputs.tf': 'outputs_tf',
        'output.tf': 'outputs_tf',
        'terraform.tfvars': 'terraform_tfvars',
        'tfvars': 'terraform_tfvars',
        'readme.md': 'README_md',
        'readme': 'README_md'
    }
    
    # Log input for debugging
    logger.debug(f"[parse_terraform_files] Input text length: {len(text)}")
    
    # Method 1: Most common format - === filename === followed by code block
    filenames_ordered = ['providers.tf', 'main.tf', 'variables.tf', 'outputs.tf', 
                         'terraform.tfvars', 'README.md']
    
    for i, tf_filename in enumerate(filenames_ordered):
        key = file_mapping.get(tf_filename.lower())
        if not key or terraform_files[key]:
            continue
        
        # Build regex to find this file's section header
        escaped_filename = tf_filename.replace('.', r'\.')
        
        # Look for header patterns like === filename === or ### filename
        header_pattern = rf'(?:===|---|\#{{1,4}})\s*{escaped_filename}\s*(?:===|---)?'
        header_match = re.search(header_pattern, text, re.IGNORECASE)
        
        if header_match:
            start_pos = header_match.end()
            remaining = text[start_pos:]
            
            # Find the NEXT file header to know where this section ends
            next_header_pos = len(remaining)
            for j in range(i + 1, len(filenames_ordered)):
                next_filename = filenames_ordered[j]
                next_escaped = next_filename.replace('.', r'\.')
                next_pattern = rf'(?:===|---|\#{{1,4}})\s*{next_escaped}\s*(?:===|---)?'
                next_match = re.search(next_pattern, remaining, re.IGNORECASE)
                if next_match:
                    next_header_pos = min(next_header_pos, next_match.start())
                    break
            
            # Also check for common end markers
            for end_marker in [r'\n---\n', r'\n\*\*\*\n', r'\n\n---', r'\nThis implementation']:
                end_match = re.search(end_marker, remaining[:next_header_pos])
                if end_match:
                    next_header_pos = min(next_header_pos, end_match.start())
            
            section_content = remaining[:next_header_pos]
            
            # Extract code from code block within this section
            code_block_match = re.search(
                r'```(?:hcl|terraform|tf|markdown|md)?\s*\n(.*?)```',
                section_content, re.DOTALL | re.IGNORECASE
            )
            
            if code_block_match:
                content = code_block_match.group(1).strip()
                if content:
                    terraform_files[key] = content
                    logger.debug(f"[parse_terraform_files] Found {tf_filename}: {len(content)} chars")
    
    # Method 2: Code blocks with filename in language tag (```hcl:providers.tf)
    code_block_with_name = re.findall(
        r'```(?:hcl|terraform|tf)?[:\s]*([a-zA-Z_\-\.]+\.(?:tf|tfvars|md))\s*\n(.*?)```',
        text, re.DOTALL | re.IGNORECASE
    )
    for filename, content in code_block_with_name:
        key = file_mapping.get(filename.lower())
        if key and not terraform_files[key]:
            terraform_files[key] = content.strip()
            logger.debug(f"[parse_terraform_files] Found via inline name {filename}: {len(content.strip())} chars")
    
    # Method 3 fallback: Look for header patterns without code blocks
    file_patterns = [
        (r'(?:===|---)\s*(', r')\s*(?:===|---)'),
        (r'#{1,4}\s*(?:File:?\s*)?(', r')'),
        (r'(?:\*\*|__)\s*(', r')\s*(?:\*\*|__)'),
        (r'(?:File|Filename)\s*:\s*(', r')'),
    ]
    
    filenames = ['providers\\.tf', 'main\\.tf', 'variables\\.tf', 'outputs\\.tf', 
                 'terraform\\.tfvars', 'README\\.md']
    
    for tf_filename in filenames:
        key = file_mapping.get(tf_filename.replace('\\', '').lower())
        if not key or terraform_files[key]:
            continue
            
        for prefix, suffix in file_patterns:
            pattern = prefix + tf_filename + suffix
            try:
                match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            except re.error:
                continue
            if match:
                start_pos = match.end()
                remaining = text[start_pos:]
                
                next_file = re.search(
                    r'(?:===|---|\#{1,4}|\*\*|__|File:|//\s*|#\s*)(?:providers|main|variables|outputs|terraform|README)\.(?:tf|tfvars|md)',
                    remaining, re.IGNORECASE
                )
                section_end = next_file.start() if next_file else len(remaining)
                section_content = remaining[:section_end]
                
                code_block = re.search(r'```(?:hcl|terraform|tf|markdown|md)?\s*\n(.*?)```', 
                                       section_content, re.DOTALL)
                if code_block:
                    terraform_files[key] = code_block.group(1).strip()
                    logger.debug(f"[parse_terraform_files] Fallback found {tf_filename}: {len(code_block.group(1).strip())} chars")
                    break
                
                content = section_content.strip()
                content = re.sub(r'^```(?:hcl|terraform|tf|markdown|md)?\s*\n?', '', content)
                content = re.sub(r'\n?```\s*$', '', content)
                
                if content and len(content) > 10:
                    terraform_files[key] = content.strip()
                    break
    
    # Method 4: If still no main.tf, try to find any terraform resource blocks
    if not terraform_files['main_tf']:
        main_blocks = []
        for block_type in ['resource', 'data', 'module', 'locals']:
            pattern = rf'({block_type}\s+["\']?[\w_-]+["\']?(?:\s+["\']?[\w_-]+["\']?)?\s*\{{)'
            for match in re.finditer(pattern, text, re.IGNORECASE):
                start = match.start()
                block_content = extract_terraform_block(text, start)
                if block_content and len(block_content) > 20:
                    main_blocks.append(block_content)
        if main_blocks:
            terraform_files['main_tf'] = '\n\n'.join(main_blocks)
            logger.debug(f"[parse_terraform_files] Extracted main.tf from resource blocks: {len(terraform_files['main_tf'])} chars")
    
    # Method 5: If still no providers.tf, look for terraform/provider blocks
    if not terraform_files['providers_tf']:
        provider_blocks = []
        for block_type in ['terraform', 'provider']:
            pattern = rf'({block_type}\s*\{{)'
            for match in re.finditer(pattern, text, re.IGNORECASE):
                start = match.start()
                block_content = extract_terraform_block(text, start)
                if block_content and len(block_content) > 10:
                    provider_blocks.append(block_content)
        if provider_blocks:
            terraform_files['providers_tf'] = '\n\n'.join(provider_blocks)
            logger.debug(f"[parse_terraform_files] Extracted providers.tf from provider blocks: {len(terraform_files['providers_tf'])} chars")
    
    # Method 6: If still no variables.tf, look for variable blocks
    if not terraform_files['variables_tf']:
        var_blocks = []
        pattern = r'(variable\s+["\']?[\w_-]+["\']?\s*\{)'
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start = match.start()
            block_content = extract_terraform_block(text, start)
            if block_content and len(block_content) > 10:
                var_blocks.append(block_content)
        if var_blocks:
            terraform_files['variables_tf'] = '\n\n'.join(var_blocks)
            logger.debug(f"[parse_terraform_files] Extracted variables.tf from variable blocks: {len(terraform_files['variables_tf'])} chars")
    
    # Method 7: If still no outputs.tf, look for output blocks
    if not terraform_files['outputs_tf']:
        output_blocks = []
        pattern = r'(output\s+["\']?[\w_-]+["\']?\s*\{)'
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start = match.start()
            block_content = extract_terraform_block(text, start)
            if block_content and len(block_content) > 10:
                output_blocks.append(block_content)
        if output_blocks:
            terraform_files['outputs_tf'] = '\n\n'.join(output_blocks)
            logger.debug(f"[parse_terraform_files] Extracted outputs.tf from output blocks: {len(terraform_files['outputs_tf'])} chars")
    
    # Log final extraction summary
    logger.info(f"[parse_terraform_files] Extraction complete. File sizes: " +
                f"providers_tf={len(terraform_files['providers_tf'])}, " +
                f"main_tf={len(terraform_files['main_tf'])}, " +
                f"variables_tf={len(terraform_files['variables_tf'])}, " +
                f"outputs_tf={len(terraform_files['outputs_tf'])}, " +
                f"terraform_tfvars={len(terraform_files['terraform_tfvars'])}, " +
                f"README_md={len(terraform_files['README_md'])}")
    
    return terraform_files
