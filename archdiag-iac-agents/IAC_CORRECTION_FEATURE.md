# IaC Correction Agent - Feature Addition

## 🎯 Overview

Added a new **IaC Correction Agent** to the archdiag-iac-agents pipeline that automatically fixes validation issues in generated Bicep code. This agent sits between the IaC Review Agent and IaC Deployment Agent, providing intelligent auto-correction capabilities.

## ✨ What's New

### New Agent: IaC Correction Agent

**Location**: `agents/iac_correction_agent.py` (400+ lines)

**Purpose**: Automatically correct issues found during Bicep code validation

**Capabilities**:
- ✅ **Syntax Error Correction**: Fixes compilation errors to ensure code compiles
- ✅ **Security Enhancement**: Applies security best practices (encryption, managed identity, HTTPS)
- ✅ **Configuration Fixes**: Corrects missing required properties and API version issues
- ✅ **Best Practices Application**: Adds tags, diagnostics, monitoring configurations
- ✅ **Intent Preservation**: Maintains original infrastructure design while fixing issues

### Key Features

1. **Intelligent Issue Categorization**
   - Critical issues (blocks deployment)
   - Error issues (should be fixed)
   - Warning issues (should be reviewed)
   - Info issues (optional improvements)

2. **AI-Powered Correction**
   - Uses GPT-4o model for intelligent fixes
   - Analyzes validation results and original code
   - Generates corrected code with `// FIXED:` comments
   - Preserves all resources, parameters, and outputs

3. **Comprehensive Correction Tracking**
   - `CorrectedBicepCode` model extends original `BicepCode`
   - Tracks corrections applied, issues fixed, remaining issues
   - Provides detailed correction notes
   - Increments version to 1.1

## 🔧 Technical Implementation

### Data Model Updates

**File**: `models/workflow_models.py`

```python
class WorkflowStage(str, Enum):
    # ... existing stages ...
    IAC_CORRECTION = "iac_correction"  # NEW

class WorkflowState(BaseModel):
    # ... existing fields ...
    corrected_bicep_code: Optional[Any] = None  # NEW
```

**New Model** (in `agents/iac_correction_agent.py`):
```python
class CorrectedBicepCode(BicepCode):
    corrections_applied: list[dict[str, Any]] = []
    original_issues_count: int = 0
    remaining_issues_count: int = 0
    correction_notes: list[str] = []
    auto_fix_success: bool = True
```

### Workflow Changes

**File**: `workflow/main_workflow.py`

**Before** (5-stage workflow):
```
ResourceAnalysis → IaCGeneration → IaCReview → IaCDeployment
```

**After** (6-stage workflow):
```
ResourceAnalysis → IaCGeneration → IaCReview → IaCCorrection → IaCDeployment
```

**Event Handler Update**:
- Detects `CorrectedBicepCode` by checking for `corrections_applied` attribute
- Updates workflow state to `IAC_CORRECTION` stage
- Stores corrected code in `workflow_state.corrected_bicep_code`

### API Enhancements

**File**: `api_server.py`

**New Endpoint**:
```
GET /api/workflow/{workflow_id}/corrected-bicep
```
- Downloads corrected Bicep code with auto-fixes
- Returns file: `infrastructure-{workflow_id}-corrected.bicep`

**Updated Status Endpoint**:
```json
{
  "corrected_bicep_code": {
    "corrections_applied": 5,
    "original_issues": 8,
    "remaining_issues": 0,
    "auto_fix_success": true,
    "download_url": "/api/workflow/{id}/corrected-bicep"
  }
}
```

**API Version**: Updated from 1.0.0 → 1.1.0

## 📋 Agent Implementation Details

### IaCCorrectionAgent Class

**Inherits**: `agent_framework.Executor`

**Main Handler**:
```python
@handler
async def correct_bicep_code(
    validation_result: ValidationResult,
    ctx: Any,
) -> CorrectedBicepCode
```

**Key Methods**:

1. `_get_bicep_from_context()` - Extracts original Bicep from workflow context
2. `_categorize_issues()` - Groups issues by severity (critical/error/warning/info)
3. `_prepare_correction_prompt()` - Creates detailed AI prompt with:
   - Original Bicep code
   - All validation issues with locations and suggestions
   - Correction requirements by severity
   - Preservation requirements
   - Code quality guidelines
4. `_apply_ai_corrections()` - Calls AI with prompt to generate corrected code
5. `_extract_bicep_from_response()` - Extracts clean Bicep from AI response
6. `_build_corrected_result()` - Constructs CorrectedBicepCode with metadata

**AI Instructions** (700+ words):
- Detailed requirements for each issue type
- Explicit preservation guidelines
- Code quality standards
- Response format specifications

### Correction Process Flow

```
1. Receive ValidationResult from IaC Review Agent
2. Extract original BicepCode from workflow context
3. Check if correction needed (skip if already valid)
4. Categorize issues by severity level
5. Prepare comprehensive AI correction prompt
6. Call AI to generate corrected code
7. Extract corrected Bicep from response
8. Build CorrectedBicepCode result with metadata
9. Return to workflow for deployment
```

## 🔄 Workflow Integration

### Agent Creation

```python
iac_correction_agent = create_iac_correction_agent(chat_client)
```

### Workflow Builder

```python
self.workflow = (
    WorkflowBuilder()
    .set_start_executor(resource_analysis_agent)
    .add_edge(resource_analysis_agent, iac_generation_agent)
    .add_edge(iac_generation_agent, iac_review_agent)
    .add_edge(iac_review_agent, iac_correction_agent)  # NEW
    .add_edge(iac_correction_agent, iac_deployment_agent)
    .build()
)
```

## 📝 Usage Examples

### API Usage

```bash
# Upload diagram and start workflow
curl -X POST "http://localhost:8000/api/diagram/upload" \
  -F "file=@diagram.png" \
  -F "resource_group=rg-test"

# Check status (includes correction info)
curl "http://localhost:8000/api/workflow/{workflow_id}"

# Download original Bicep
curl "http://localhost:8000/api/workflow/{workflow_id}/bicep" \
  -o original.bicep

# Download corrected Bicep
curl "http://localhost:8000/api/workflow/{workflow_id}/corrected-bicep" \
  -o corrected.bicep
```

### Python Usage

```python
from workflow import run_workflow

result = await run_workflow("diagram.png", "rg-test", "eastus")

# Check correction results
if result.corrected_bicep_code:
    print(f"Corrections applied: {len(result.corrected_bicep_code.corrections_applied)}")
    print(f"Original issues: {result.corrected_bicep_code.original_issues_count}")
    print(f"Auto-fix success: {result.corrected_bicep_code.auto_fix_success}")
    
    # Save corrected code
    with open("infrastructure-corrected.bicep", "w") as f:
        f.write(result.corrected_bicep_code.bicep_code)
```

## 🎨 Example Corrections

### Syntax Error Fix

**Before** (from IaC Generation):
```bicep
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageName  // Missing quotes
  location: location
  sku: {
    name: 'Standard_LRS
  }
}
```

**After** (Corrected):
```bicep
// FIXED: Added quotes to storage account name
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'storageName'
  location: location
  sku: {
    // FIXED: Closed string quote
    name: 'Standard_LRS'
  }
}
```

### Security Enhancement

**Before**:
```bicep
resource webApp 'Microsoft.Web/sites@2023-01-01' = {
  name: webAppName
  location: location
  properties: {
    httpsOnly: false  // Security issue
  }
}
```

**After**:
```bicep
resource webApp 'Microsoft.Web/sites@2023-01-01' = {
  name: webAppName
  location: location
  properties: {
    // FIXED: Enabled HTTPS-only for security
    httpsOnly: true
    // FIXED: Added managed identity
    identity: {
      type: 'SystemAssigned'
    }
  }
}
```

## 📦 Files Modified/Created

### New Files (1)
- `agents/iac_correction_agent.py` - Complete agent implementation (400+ lines)

### Modified Files (6)
1. `agents/__init__.py` - Added IaCCorrectionAgent exports
2. `models/workflow_models.py` - Added IAC_CORRECTION stage and corrected_bicep_code field
3. `workflow/main_workflow.py` - Integrated correction agent into pipeline
4. `api_server.py` - Added `/corrected-bicep` endpoint and status updates
5. `README.md` - Updated architecture diagram, endpoints, project structure
6. `PROJECT_COMPLETE.md` - Updated feature list, file count, workflow diagram

### Total Changes
- **Lines Added**: ~500+
- **Files Modified**: 6
- **New Endpoints**: 1
- **New Models**: 1 (CorrectedBicepCode)
- **New Agents**: 1 (IaCCorrectionAgent)

## ✅ Benefits

1. **Reduced Manual Intervention**: Automatically fixes common issues without human review
2. **Faster Deployment**: Valid code ready for deployment without round-trips
3. **Learning from Best Practices**: AI applies Azure best practices consistently
4. **Audit Trail**: All corrections documented with `// FIXED:` comments
5. **Flexibility**: Users can choose original or corrected Bicep for deployment
6. **Safety**: Original code preserved; corrections are additive

## 🚀 Next Steps

### Potential Enhancements
1. **Re-validation**: Run IaC Review Agent on corrected code to verify fixes
2. **User Approval**: Add workflow step for human review before deployment
3. **Correction History**: Store multiple correction attempts with versioning
4. **Custom Rules**: Allow users to define custom correction rules
5. **Rollback**: Support reverting to original code if corrections fail
6. **Metrics**: Track correction success rates and common issue patterns

## 📚 Documentation Updates

- ✅ README.md architecture diagram updated to show 6 stages
- ✅ API endpoints documentation includes new `/corrected-bicep` endpoint
- ✅ Project structure shows new `iac_correction_agent.py`
- ✅ Usage examples include corrected Bicep downloads
- ✅ PROJECT_COMPLETE.md reflects 6-agent system

---

**Feature Status**: ✅ **COMPLETE**

The IaC Correction Agent is fully integrated and ready for use. It enhances the workflow by providing intelligent auto-correction of validation issues, making the system more robust and reducing manual intervention required for deployment.
