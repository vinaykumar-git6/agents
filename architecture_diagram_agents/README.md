# Architecture Diagram Analyzer

AI-powered architecture diagram analyzer that generates Infrastructure as Code (Terraform) from architecture diagrams using **Microsoft Agent Framework** and **Azure Computer Vision**.

## 🚀 Features

- ✅ **AI-Powered Analysis**: Extracts architecture components using Azure Computer Vision
- ✅ **Multi-Agent Workflow**: 4-stage collaborative pipeline with Microsoft Agent Framework
- ✅ **Real-Time Progress Tracking**: Server-Sent Events (SSE) for live agent monitoring
- ✅ **Terraform Generation**: Automated Infrastructure as Code with proper file structure
- ✅ **Cost Estimation**: Infrastructure cost analysis using Infracost CLI
- ✅ **Best Practices Validation**: Azure Well-Architected Framework recommendations
- ✅ **Interactive DevUI**: Real-time 4-panel dashboard for agent execution monitoring
- ✅ **Asynchronous Background Processing**: Non-blocking IAC generation with job tracking

## 🏗️ Architecture

### Multi-Agent Workflow Pipeline

```
1. Vision Analyzer (Agent 1/4)
   ↓ Extracts: Objects, Tags, Text, Architecture Type
   
2. Service Analyzer (Agent 2/4)
   ↓ Identifies: Azure Services, Cloud Provider, Region
   
3. Best Practices (Agent 3/4)
   ↓ Generates: Recommendations, Architecture Checklist
   
4. IAC Group Chat (Agent 4/4)
   ├── Generator Agent: Creates Terraform code
   ├── Reviewer Agent: Validates and refines
   └── Infracost Agent: Estimates infrastructure costs
       ↓ Output: providers.tf, main.tf, variables.tf, outputs.tf, terraform.tfvars, infracost.json
```

### Project Structure

```
architecture_diagram_agents/
├── agents/                     # AI Agent implementations
│   ├── vision_agent.py        # Azure Computer Vision integration
│   ├── analyzer_agent.py      # Service identification agent
│   ├── azure_best_practice_agent.py  # Azure WAF recommendations
│   ├── iac_generator_agent.py # Terraform code generator
│   ├── iac_reviewer_agent.py  # Code review and validation
│   └── infracost_agent.py     # Infrastructure cost estimation
│
├── workflows/                  # Workflow orchestration
│   └── orchestrator.py        # 4-stage pipeline with SSE progress
│
├── core/                       # Core infrastructure
│   ├── config.py              # Configuration management
│   ├── models.py              # Data models
│   └── exceptions.py          # Custom exceptions
│
├── utils/                      # Utilities
│   ├── logging_config.py      # Centralized logging
│   ├── retry_handler.py       # Retry logic for Azure APIs
│   ├── validators.py          # Input validation
│   └── legacy_utils.py        # Helper functions
│
├── templates/                  # Web UI
│   ├── index.html             # Main UI with real-time updates
│   └── devui.html             # 4-panel agent monitoring dashboard
│
└── app.py                      # Flask web server with SSE endpoints
```

## 🎯 Quick Start

### Prerequisites

- Python 3.9+
- Azure subscription with Computer Vision resource
- Azure CLI (for authentication)
- Azure AI Foundry project (for Agent Framework)

### Installation

```bash
# Clone repository
cd InnovationHub

# Create virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1  # Windows
# source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

### Configuration

Create `.env` file in project root:

```env
# Azure Computer Vision
AZURE_COMPUTER_VISION_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
AZURE_COMPUTER_VISION_REGION=eastus

# Azure AI Foundry (Agent Framework)
PROJECT_CONNECTION_STRING=your-foundry-project-connection-string
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
AZURE_OPENAI_API_VERSION=2024-05-01-preview

# Infracost (for cost estimation)
INFRACOST_API_KEY=your-infracost-api-key

# Flask Configuration
FLASK_SECRET_KEY=your-secret-key-here
```

### Run Application

```bash
# From project root
python -m architecture_diagram_agents.app

# Or using Flask directly
flask --app architecture_diagram_agents.app run --port 5000
```

Visit `http://localhost:5000`

## 📖 Usage

### Web UI Workflow

1. **Upload Diagram**: Drag & drop or select architecture diagram image
2. **Start Analysis**: Click "Analyze Architecture" 
3. **Monitor Progress**: Click "🔍 Watch Agents Live" floating button
4. **View Results**: 
   - Architecture analysis summary
   - Azure services identified
   - Best practices recommendations
   - Generated Terraform files
5. **Download**: Get complete Terraform project as ZIP

### API Endpoints

#### Complete Workflow (Analysis + IAC)
```bash
POST /analyze
Content-Type: multipart/form-data

# Returns job_id for progress tracking
{
  "job_id": "uuid-v4",
  "vision_result": {...},
  "analyzer_result": {...},
  "best_practices": {...}
}
```

#### Analysis Only (No IAC)
```bash
POST /analyze-only
Content-Type: multipart/form-data

# Faster response, no Terraform generation
```

#### Real-Time Progress Stream
```bash
GET /progress/<job_id>
Accept: text/event-stream

# SSE events:
# - executor_start
# - agent_action
# - executor_complete
# - executor_error
# - workflow_complete
```

#### IAC Generation Status
```bash
GET /iac-status/<job_id>

# Returns:
{
  "status": "running|completed|failed",
  "result": {...},
  "error": null
}
```

#### Download Terraform
```bash
GET /download-terraform?job_id=<uuid>

# Returns: terraform_project.zip
```

### DevUI Monitoring

The DevUI provides real-time visibility into agent execution:

- **4 Panel Layout**: One panel per workflow stage
- **Live Metrics**: Objects, Services, Recommendations, Rounds, Files
- **Activity Logs**: Timestamped agent actions with auto-scroll
- **Status Badges**: IDLE → RUNNING → COMPLETED/FAILED transitions
- **SSE Connection**: Automatic reconnection with heartbeat

Access: Click floating "🔍 Watch Agents Live" button or visit `/devui`

## 🔧 Development

### Running Tests

```bash
# Install dev dependencies
pip install pytest pytest-asyncio black ruff

# Run tests
pytest

# With coverage
pytest --cov=architecture_diagram_agents
```

### Code Formatting

```bash
# Format code
black architecture_diagram_agents/

# Lint
ruff check architecture_diagram_agents/
```

### Debugging Agents

Enable detailed logging in `.env`:

```env
LOG_LEVEL=DEBUG
```

Monitor logs in terminal and DevUI for:
- Azure API calls
- Agent execution traces
- Workflow state transitions
- Error stack traces

## 🏛️ Agent Framework Integration

### Vision Agent

```python
from architecture_diagram_agents.agents.vision_agent import VisionAgent

agent = VisionAgent()
result = await agent.execute({
    "image_path": "path/to/diagram.png",
    "features": ["objects", "tags", "text", "dense_captions"]
})
```

### Workflow Orchestrator

```python
from architecture_diagram_agents.workflows.orchestrator import WorkflowOrchestrator

orchestrator = WorkflowOrchestrator()
result = await orchestrator.execute_workflow({
    "image_path": "diagram.png",
    "analysis_type": "complete",
    "job_id": "optional-uuid"
})
```

## 📊 Output Structure

### Terraform Project

```
terraform_projects/<job_id>/
├── providers.tf          # Azure provider configuration
├── main.tf               # Resource definitions
├── variables.tf          # Input variables
├── outputs.tf            # Output values
├── terraform.tfvars      # Variable values
├── plan.json             # Terraform plan (if generated)
└── infracost.json        # Cost breakdown
```

### Analysis Results

```json
{
  "vision_result": {
    "text": ["extracted text"],
    "objects": [{"name": "VM", "confidence": 0.95}],
    "tags": ["azure", "networking"],
    "architecture_type": "Three-tier web application"
  },
  "analyzer_result": {
    "cloud_provider": "Azure",
    "default_region": "East US",
    "azure_services": [
      {"name": "Virtual Network", "category": "Networking"},
      {"name": "App Service", "category": "Compute"}
    ],
    "total_services": 8
  },
  "best_practices": {
    "service_recommendations": [
      "Enable Azure Firewall for network security",
      "Implement Azure Key Vault for secrets"
    ],
    "architecture_checklist": [...]
  },
  "terraform_files": {
    "providers.tf": "...",
    "main.tf": "..."
  }
}
```

## 🔒 Security Best Practices

- **Authentication**: Uses Azure CLI credential (DefaultAzureCredential)
- **Secrets Management**: Environment variables, never hardcoded
- **HTTPS Required**: Production deployment with TLS/SSL
- **File Upload Validation**: Size limits (16MB), extension checks
- **Session Security**: Flask secret key for session encryption

## 🐛 Troubleshooting

### Common Issues

**"Azure Computer Vision authentication failed"**
```bash
# Login to Azure CLI
az login
az account set --subscription <subscription-id>
```

**"Agent Framework module not found"**
```bash
# Install with preview flag
pip install --pre agent-framework-azure-ai
```

**"Infracost not found or API key missing"**
```bash
# Install Infracost CLI
# Windows: choco install infracost
# Mac: brew install infracost
# Linux: curl -fsSL https://raw.githubusercontent.com/infracost/infracost/master/scripts/install.sh | sh

# Set API key in .env
INFRACOST_API_KEY=your-api-key
```

**"SSE connection drops"**
- Check browser console for errors
- Verify job_id in sessionStorage
- Monitor Flask logs for queue issues

**"Terraform files all in main.tf"**
- Fixed in latest version with enhanced parser
- Supports both `===` markers and `###` markdown headers

## 📚 Dependencies

### Core
- `flask==3.1.2` - Web framework
- `azure-ai-vision-imageanalysis==1.0.0` - Computer Vision SDK
- `azure-identity==1.25.1` - Azure authentication
- `agent-framework-azure-ai>=1.0.0b251120` - Microsoft Agent Framework
- `python-dotenv==1.2.1` - Environment management

### Development
- `pytest>=8.0.0` - Testing framework
- `black>=24.0.0` - Code formatter
- `ruff>=0.6.0` - Fast linter

See `requirements.txt` for complete list.

## 🤝 Contributing

1. Follow existing code structure
2. Add type hints and docstrings
3. Write tests for new features
4. Format code with `black`
5. Ensure all agents follow `BaseAgent` interface

## 📝 License

MIT License - See LICENSE file for details

## 🙋 Support

For issues or questions:
- Check DevUI logs for agent execution details
- Review Flask console for backend errors
- Enable DEBUG logging for detailed traces
- Verify Azure resource permissions
