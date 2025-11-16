# Architecture Diagram to IaC Agents

**AI-Powered Infrastructure as Code Generation from Architecture Diagrams**

Automatically convert Azure architecture diagrams into production-ready Bicep infrastructure code using a multi-agent AI system powered by Microsoft Agent Framework.

## 🎯 Overview

This project implements a complete AI agent workflow that:
1. **Analyzes** architecture diagrams using Azure Computer Vision
2. **Synthesizes** resource specifications with intelligent analysis
3. **Generates** production-ready Bicep infrastructure as code
4. **Reviews** and validates code using Azure best practices
5. **Corrects** issues automatically with AI-powered auto-fix
6. **Deploys** infrastructure to Azure with full monitoring

## 🏗️ Architecture

```
┌─────────────────┐
│  Architecture   │
│    Diagram      │
│   (PNG/JPEG)    │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│          Stage 1: Computer Vision Analysis              │
│  • Extract text and objects from diagram                │
│  • Identify Azure services and resource types           │
│  • Detect connections and relationships                 │
└────────┬────────────────────────────────────────────────┘
         │ DiagramAnalysis
         ▼
┌─────────────────────────────────────────────────────────┐
│          Stage 2: Resource Analysis Agent               │
│  • Normalize resource names and configurations          │
│  • Resolve dependencies and deployment order            │
│  • Apply Azure naming conventions                       │
│  • Enrich with best practices                           │
└────────┬────────────────────────────────────────────────┘
         │ ResourceSpecification
         ▼
┌─────────────────────────────────────────────────────────┐
│          Stage 3: IaC Generation Agent                  │
│  • Generate complete Bicep templates                    │
│  • Create parameters, variables, outputs                │
│  • Apply security configurations                        │
│  • Follow Azure Well-Architected Framework              │
└────────┬────────────────────────────────────────────────┘
         │ BicepCode
         ▼
┌─────────────────────────────────────────────────────────┐
│          Stage 4: IaC Review Agent                      │
│  • Validate Bicep syntax with Azure CLI                 │
│  • Check security best practices                        │
│  • Run linter and compliance checks                     │
│  • Use Azure MCP tools for validation                   │
└────────┬────────────────────────────────────────────────┘
         │ ValidationResult
         ▼
┌─────────────────────────────────────────────────────────┐
│          Stage 5: IaC Correction Agent (NEW)            │
│  • Automatically fix syntax errors                      │
│  • Apply security best practices                        │
│  • Correct configuration issues                         │
│  • Add missing required properties                      │
└────────┬────────────────────────────────────────────────┘
         │ CorrectedBicepCode
         ▼
┌─────────────────────────────────────────────────────────┐
│          Stage 6: IaC Deployment Agent                  │
│  • Deploy corrected code to Azure                       │
│  • Monitor deployment progress                          │
│  • Collect outputs and resource IDs                     │
│  • Handle errors and provide remediation                │
└────────┬────────────────────────────────────────────────┘
         │ DeploymentResult
         ▼
    ✅ Infrastructure Deployed
```

## ✨ Key Features

### Multi-Agent AI System
- **Microsoft Agent Framework** for robust agent orchestration
- **Azure AI Foundry** for advanced language model capabilities
- **Streaming workflow** execution with real-time monitoring
- **Type-safe** data models with Pydantic validation

### Intelligent Analysis
- **Computer Vision** powered resource detection
- **AI-driven** resource normalization and enrichment
- **Dependency resolution** with deployment ordering
- **Best practices** applied automatically

### Production-Ready Code Generation
- **Complete Bicep templates** with parameters and outputs
- **Security-first** configurations (encryption, HTTPS, managed identity)
- **Latest API versions** for all Azure resources
- **Well-documented** code with inline comments

### Comprehensive Validation
- **Syntax validation** using Azure CLI
- **Security scanning** for misconfigurations
- **Best practices** compliance checking
- **Azure MCP tools** integration for advanced validation

### Automated Deployment
- **Azure SDK** powered deployment
- **Resource group** creation and management
- **Deployment monitoring** with detailed logging
- **Error analysis** with AI-powered remediation suggestions

## 📋 Prerequisites

- **Python 3.11+**
- **Azure CLI** (for Bicep compilation and deployment)
- **Azure Subscription** with appropriate permissions
- **Azure Services**:
  - Azure AI Foundry project with model deployment
  - Azure Computer Vision service
  - Resource creation permissions

## 🚀 Quick Start

### 1. Installation

```powershell
# Clone or navigate to the project
cd archdiag-iac-agents

# Create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies (note: --pre flag required for Agent Framework)
pip install -r requirements.txt

# Install Azure CLI if not already installed
# Download from: https://learn.microsoft.com/cli/azure/install-azure-cli
```

### 2. Configuration

```powershell
# Copy environment template
cp .env.template .env

# Edit .env with your Azure resource details
# Required:
# - AZURE_AI_PROJECT_ENDPOINT
# - AZURE_AI_MODEL_DEPLOYMENT_NAME
# - AZURE_COMPUTER_VISION_ENDPOINT
# - AZURE_SUBSCRIPTION_ID
```

### 3. Azure Authentication

```powershell
# Login to Azure (uses DefaultAzureCredential)
az login

# Set your subscription
az account set --subscription "your-subscription-id"

# Verify authentication
az account show
```

### 4. Run the Workflow

#### Option A: API Server (Recommended)

```powershell
# Start the FastAPI server
python api_server.py

# Server runs on http://localhost:8000
# Open browser to http://localhost:8000 for API docs
```

Upload diagram via API:
```powershell
# Upload architecture diagram
curl -X POST "http://localhost:8000/api/diagram/upload" `
  -F "file=@path/to/your/diagram.png" `
  -F "resource_group=rg-my-infrastructure" `
  -F "location=eastus"

# Check workflow status
curl "http://localhost:8000/api/workflow/{workflow_id}"

# Download original generated Bicep
curl "http://localhost:8000/api/workflow/{workflow_id}/bicep" -o infrastructure.bicep

# Download corrected Bicep (auto-fixed)
curl "http://localhost:8000/api/workflow/{workflow_id}/corrected-bicep" -o infrastructure-corrected.bicep
```

#### Option B: Direct Python Execution

```python
import asyncio
from workflow import run_workflow

async def main():
    result = await run_workflow(
        image_path="samples/architecture-diagram.png",
        resource_group="rg-test-infrastructure",
        location="eastus"
    )
    
    print(f"Workflow: {result.workflow_id}")
    print(f"Status: {result.current_stage.value}")
    
    if result.bicep_code:
        print(f"Bicep Code Generated:")
        print(result.bicep_code.bicep_code)
    
    if result.deployment_result:
        print(f"Deployment Status: {result.deployment_result.status.value}")
        print(f"Resources Deployed: {result.deployment_result.total_resources}")

asyncio.run(main())
```

## 📁 Project Structure

```
archdiag-iac-agents/
├── agents/                      # AI Agent implementations
│   ├── resource_analysis_agent.py   # Resource normalization & analysis
│   ├── iac_generation_agent.py      # Bicep code generation
│   ├── iac_review_agent.py          # Validation & security review
│   ├── iac_correction_agent.py      # Auto-fix validation issues (NEW)

│   └── iac_deployment_agent.py      # Azure deployment
├── config/                      # Configuration management
│   └── settings.py              # Pydantic settings
├── models/                      # Data models
│   └── workflow_models.py       # Complete workflow models
├── utils/                       # Utilities
│   └── vision_service.py        # Computer Vision integration
├── workflow/                    # Workflow orchestration
│   └── main_workflow.py         # Main workflow coordinator
├── api_server.py                # FastAPI REST API
├── requirements.txt             # Python dependencies
├── .env.template                # Environment variables template
└── README.md                    # This file
```

## 🔧 Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `AZURE_AI_PROJECT_ENDPOINT` | Azure AI Foundry project endpoint | Yes |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | Model deployment name (e.g., gpt-4o) | Yes |
| `AZURE_COMPUTER_VISION_ENDPOINT` | Computer Vision service endpoint | Yes |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription for deployments | Yes |
| `AZURE_RESOURCE_GROUP` | Default resource group | No |
| `AZURE_LOCATION` | Default Azure region | No |
| `ENABLE_AUTO_DEPLOY` | Auto-deploy without approval | No |
| `REQUIRE_REVIEW_APPROVAL` | Require human approval | No |

### Azure Resources Setup

1. **Create Azure AI Foundry Project**:
   ```powershell
   # Using Azure Portal or CLI
   az ml workspace create --name my-ai-project --resource-group rg-ai
   ```

2. **Deploy AI Model**:
   - Navigate to Azure AI Foundry Studio
   - Deploy GPT-4o or similar model
   - Note the endpoint and deployment name

3. **Create Computer Vision Service**:
   ```powershell
   az cognitiveservices account create \
     --name my-vision-service \
     --resource-group rg-ai \
     --kind ComputerVision \
     --sku S1 \
     --location eastus
   ```

## 📊 API Endpoints

### POST /api/diagram/upload
Upload architecture diagram and start workflow.

**Request**:
```bash
POST /api/diagram/upload
Content-Type: multipart/form-data

file: <diagram-image>
resource_group: "rg-infrastructure" (optional)
location: "eastus" (optional)
auto_deploy: false (optional)
```

**Response**:
```json
{
  "workflow_id": "workflow-abc123",
  "status": "accepted",
  "message": "Diagram upload successful. Processing started.",
  "check_status_url": "/api/workflow/workflow-abc123"
}
```

### GET /api/workflow/{workflow_id}
Get workflow status and progress.

**Response**:
```json
{
  "workflow_id": "workflow-abc123",
  "status": "iac_generation",
  "started_at": "2025-11-16T10:30:00Z",
  "is_completed": false,
  "diagram_analysis": {
    "resources_detected": 5,
    "confidence": 0.85
  },
  "resource_specification": {
    "total_resources": 5,
    "resource_types": {"Microsoft.Storage/storageAccounts": 1, ...}
  }
}
```

### GET /api/workflow/{workflow_id}/bicep
Download original generated Bicep code.

**Response**: Bicep file content

### GET /api/workflow/{workflow_id}/corrected-bicep
Download corrected Bicep code with auto-fixes applied.

### GET /api/workflow/{workflow_id}/results
Get complete workflow results.

## 🔒 Security Best Practices

### Authentication
- **Managed Identity**: Preferred for all Azure services
- **DefaultAzureCredential**: Supports multiple auth methods
- **No keys in code**: All credentials via environment variables

### Generated Code Security
- HTTPS-only configurations
- Encryption at rest enabled by default
- Network security groups configured
- Managed identities for services
- Key Vault integration for secrets

### API Security
- CORS configured (update for production)
- File upload validation (type, size)
- Workflow isolation
- Error message sanitization

## 🧪 Testing

### Unit Tests (Coming Soon)
```powershell
pytest tests/
```

### Manual Testing
1. Use sample architecture diagrams from `samples/` directory
2. Test each stage independently
3. Validate generated Bicep with `az bicep build`
4. Deploy to test resource group first

## 🐛 Troubleshooting

### Agent Framework Installation
```powershell
# Ensure --pre flag is used
pip install agent-framework-azure-ai --pre

# If issues persist, upgrade pip
python -m pip install --upgrade pip
```

### Azure CLI Errors
```powershell
# Ensure Azure CLI is installed
az --version

# Re-authenticate if needed
az logout
az login
```

### Computer Vision Errors
- Verify endpoint URL (should end with `/`)
- Check API key or managed identity permissions
- Ensure image format is supported (PNG, JPEG, BMP, TIFF)

### Deployment Failures
- Verify subscription permissions
- Check resource quotas in target region
- Review Bicep validation errors
- Check deployment logs in Azure Portal

## 📚 Resources

- [Microsoft Agent Framework](https://github.com/microsoft/agent-framework)
- [Azure AI Foundry Documentation](https://learn.microsoft.com/azure/ai-studio/)
- [Azure Computer Vision API](https://learn.microsoft.com/azure/ai-services/computer-vision/)
- [Bicep Documentation](https://learn.microsoft.com/azure/azure-resource-manager/bicep/)
- [Azure Well-Architected Framework](https://learn.microsoft.com/azure/well-architected/)

## 🤝 Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## 📄 License

MIT License - See LICENSE file for details

## 🎓 Learn More

This project demonstrates:
- **Microsoft Agent Framework** multi-agent orchestration
- **Azure AI services** integration
- **Infrastructure as Code** best practices
- **Production-ready** AI application architecture
- **FastAPI** for RESTful APIs
- **Pydantic** for data validation

---

**Built with ❤️ using:**
- Microsoft Agent Framework (Python)
- Azure AI Foundry (GPT-4o)
- Azure Computer Vision
- Azure Resource Manager
- FastAPI
- Pydantic

**Important Notes:**
- ⚠️ Use `--pre` flag when installing agent-framework-azure-ai (preview)
- ⚠️ Test in non-production environment first
- ⚠️ Review generated code before deployment
- ⚠️ Configure CORS appropriately for production
