# Incident Management Agent System

> **Automated incident management using Microsoft Agent Framework and Azure AI**

## 🎯 Overview

This project implements an intelligent, automated incident management system that receives ServiceNow incident webhooks and automatically analyzes, plans, and executes remediation actions using a multi-agent architecture built with Microsoft Agent Framework.

### Key Features

- ✅ **Automated Incident Analysis** - AI agent analyzes ServiceNow incidents and identifies root causes
- ✅ **Intelligent Remediation Planning** - Searches knowledge base and creates action plans
- ✅ **Human-in-the-Loop Approval** - Email-based approval workflow for safety
- ✅ **Automated Remediation Execution** - Executes approved plans via Azure Functions
- ✅ **Root Cause Analysis & Documentation** - Updates ServiceNow with RCA and resolution details
- ✅ **Full Observability** - Tracks workflow state in Cosmos DB with detailed logging

## 🏗️ Architecture

```
ServiceNow Incident → Webhook Server → Agent Workflow
                                           ↓
                        ┌─────────────────────────────────┐
                        │  1. Incident Analysis Agent     │
                        │     (Analyzes & summarizes)     │
                        └──────────────┬──────────────────┘
                                       ↓
                        ┌─────────────────────────────────┐
                        │  2. Remediation Planning Agent  │
                        │     (Searches KB, creates plan) │
                        └──────────────┬──────────────────┘
                                       ↓
                        ┌─────────────────────────────────┐
                        │  3. Human Approval Executor     │
                        │     (Email approval workflow)   │
                        └──────────────┬──────────────────┘
                                       ↓
                        ┌─────────────────────────────────┐
                        │  4. Remediation Execution Agent │
                        │     (Invokes Azure Functions)   │
                        └──────────────┬──────────────────┘
                                       ↓
                        ┌─────────────────────────────────┐
                        │  5. ServiceNow Update Agent     │
                        │     (RCA & resolution update)   │
                        └─────────────────────────────────┘
```

### Azure Services Used

- **Azure AI Foundry** - Hosts AI models for agent intelligence
- **Azure Cosmos DB** - Stores workflow state, incidents, and approvals
- **Azure AI Search** - Remediation knowledge base
- **Azure Communication Services** - Email notifications for approvals
- **Azure Functions** - Executes remediation actions on Azure resources
- **Azure Monitor** - Application logging and monitoring

## 📋 Prerequisites

### Required Azure Resources

1. **Azure AI Foundry Project**
   - Create a project in Azure AI Foundry
   - Deploy a model (e.g., gpt-4o-mini)
   - Note the project endpoint and model deployment name

2. **Azure Cosmos DB Account**
   - Create account with Azure AD authentication (no keys)
   - Database and containers will be created automatically

3. **Azure AI Search Service**
   - Create search service
   - Create index: `remediation-knowledge-base`
   - Upload knowledge base documents

4. **Azure Communication Services**
   - Create ACS resource
   - Configure email domain
   - Note connection string and sender email

5. **Azure Function App** (for remediation actions)
   - Create Python function app
   - Enable managed identity
   - Grant RBAC permissions for resource management

### Local Development

- Python 3.11 or higher
- Azure CLI (authenticated)
- Visual Studio Code (recommended)

## 🚀 Getting Started

### 1. Clone and Setup

```powershell
# Navigate to project directory
cd incident-management-agents

# Create virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install dependencies (note: --pre flag required for agent-framework)
pip install -r requirements.txt
```

### 2. Configure Environment

```powershell
# Copy template
cp .env.template .env

# Edit .env with your Azure resource details
notepad .env
```

**Required Environment Variables:**

```env
# Azure AI Foundry
AZURE_AI_PROJECT_ENDPOINT=https://your-project.cognitiveservices.azure.com/
AZURE_AI_MODEL_DEPLOYMENT_NAME=gpt-4o-mini

# Cosmos DB (AAD only - no keys)
COSMOS_ENDPOINT=https://your-cosmosdb-account.documents.azure.com:443/
COSMOS_DATABASE_NAME=IncidentManagementDB

# Azure AI Search
AZURE_SEARCH_ENDPOINT=https://your-search-service.search.windows.net
AZURE_SEARCH_INDEX_NAME=remediation-knowledge-base

# Azure Communication Services
AZURE_COMMUNICATION_CONNECTION_STRING=endpoint=https://...
AZURE_COMMUNICATION_SENDER_EMAIL=donotreply@your-domain.azurecomm.net

# ServiceNow
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
SERVICENOW_API_USER=your-user
SERVICENOW_API_PASSWORD=your-password

# Azure Functions (Remediation)
AZURE_FUNCTIONS_REMEDIATION_URL=https://your-functionapp.azurewebsites.net

# Approval Settings
APPROVAL_REQUIRED_EMAILS=admin1@company.com,admin2@company.com
APPROVAL_TIMEOUT_MINUTES=30

# Application Insights
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=...

# Webhook Server
WEBHOOK_SERVER_HOST=0.0.0.0
WEBHOOK_SERVER_PORT=8000
WEBHOOK_SECRET_TOKEN=your-webhook-secret-token
```

### 3. Create Cosmos DB Containers

```python
# Run this once to create database and containers
python -c "
from utils.cosmos_client import cosmos_service
import asyncio
asyncio.run(cosmos_service.create_database_and_containers())
"
```

### 4. Run the Webhook Server

```powershell
# Start the FastAPI webhook server
python webhook_server.py

# Or with uvicorn directly
uvicorn webhook_server:app --host 0.0.0.0 --port 8000 --reload
```

Server will start at: `http://localhost:8000`

- Health check: `http://localhost:8000/health`
- API docs: `http://localhost:8000/docs`

### 5. Deploy Azure Functions

```powershell
# Navigate to Azure Functions directory
cd azure_functions

# Deploy to Azure
func azure functionapp publish your-functionapp-name

# Or test locally
func start
```

### 6. Test the Workflow

```powershell
# Test with sample incident
python workflow/incident_workflow.py
```

Or send a POST request to the webhook:

```powershell
$incident = @{
    sys_id = "test_123"
    number = "INC0012345"
    short_description = "Application server not responding"
    description = "Users unable to access portal"
    priority = "2"
    urgency = "2"
    impact = "2"
    category = "Infrastructure"
    subcategory = "Server"
    configuration_item = "PROD-APP-SERVER-01"
    state = "2"
    opened_at = "2025-11-14T10:30:00Z"
} | ConvertTo-Json

Invoke-WebRequest -Uri "http://localhost:8000/webhook/servicenow/incident" `
    -Method POST `
    -Body $incident `
    -ContentType "application/json"
```

## 📦 Project Structure

```
incident-management-agents/
├── agents/
│   ├── incident_analysis_agent.py        # Analyzes incidents
│   ├── remediation_planning_agent.py     # Creates remediation plans
│   ├── human_approval_executor.py        # Manages approvals
│   ├── remediation_execution_agent.py    # Executes remediation
│   └── servicenow_update_agent.py        # Updates ServiceNow
├── azure_functions/
│   └── function_app.py                    # Remediation functions
├── config/
│   └── settings.py                        # Configuration management
├── models/
│   └── incident_models.py                 # Data models
├── utils/
│   ├── cosmos_client.py                   # Cosmos DB service
│   ├── search_client.py                   # Azure AI Search service
│   └── email_service.py                   # Email notifications
├── workflow/
│   └── incident_workflow.py               # Main workflow orchestrator
├── webhook_server.py                      # FastAPI webhook server
├── requirements.txt                       # Python dependencies
├── .env.template                          # Environment variables template
└── README.md                              # This file
```

## 🔐 Security & Authentication

### Azure AD Authentication

All Azure services use **Managed Identity** or **Azure CLI credentials** (no keys):

- **Cosmos DB**: AAD authentication with `DefaultAzureCredential`
- **Azure AI Search**: AAD authentication
- **Azure Functions**: Managed identity with RBAC permissions

### Required RBAC Roles

Assign these roles to your managed identity or service principal:

```powershell
# Azure AI Foundry
az role assignment create --role "Azure AI Developer" --assignee <principal-id>

# Cosmos DB
az cosmosdb sql role assignment create \
  --account-name <cosmos-account> \
  --resource-group <rg-name> \
  --scope "/" \
  --principal-id <principal-id> \
  --role-definition-name "Cosmos DB Built-in Data Contributor"

# Azure Functions (for remediation)
az role assignment create --role "Contributor" --assignee <principal-id> --scope <resource-scope>
```

### Webhook Security

Webhooks are secured with HMAC-SHA256 signatures:

```python
# ServiceNow should include signature header
X-ServiceNow-Signature: <hmac-sha256-hex>
```

## 🧪 Testing

### Test Individual Agents

```python
# Test incident analysis agent
from agents.incident_analysis_agent import create_incident_analysis_agent
from azure.identity.aio import DefaultAzureCredential

credential = DefaultAzureCredential()
agent = await create_incident_analysis_agent(credential)
# Run test...
```

### Test Complete Workflow

```python
python workflow/incident_workflow.py
```

### Test Webhook Endpoint

Use the included test script or curl:

```bash
curl -X POST http://localhost:8000/webhook/servicenow/incident \
  -H "Content-Type: application/json" \
  -d @test_incident.json
```

## 📊 Monitoring & Logging

### Application Insights

All agents log to Application Insights for monitoring:

- Workflow execution traces
- Agent performance metrics
- Error tracking and alerts
- Custom events for each stage

### Cosmos DB Queries

Query workflow state:

```sql
SELECT * FROM c WHERE c.incident_number = "INC0012345"
```

Query approvals:

```sql
SELECT * FROM c WHERE c.status = "pending" AND c.expires_at > GetCurrentDateTime()
```

## 🔧 Troubleshooting

### Common Issues

**1. "DefaultAzureCredential failed to retrieve a token"**
- Run: `az login`
- Ensure you have proper RBAC roles assigned

**2. "Cosmos DB Unauthorized (401)"**
- Verify Cosmos DB has AAD authentication enabled
- Check RBAC role assignments
- Wait 5-10 minutes for role propagation

**3. "Agent Framework import errors"**
- Ensure you used `--pre` flag: `pip install agent-framework-azure-ai --pre`

**4. "Approval emails not sending"**
- Verify Azure Communication Services connection string
- Check sender email domain is verified
- Review ACS service quotas

**5. "Azure Functions timing out"**
- Increase function timeout in host.json
- Check managed identity permissions
- Review function logs in Azure Portal

### Debug Mode

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 📖 Documentation

### Microsoft Agent Framework

- [GitHub Repository](https://github.com/microsoft/agent-framework)
- [Documentation](https://microsoft.github.io/agent-framework/)
- Installation: `pip install agent-framework-azure-ai --pre`

### API Endpoints

**Webhook Server:**

- `POST /webhook/servicenow/incident` - Receive incident webhooks
- `POST /api/approval/{approval_id}` - Handle approval responses
- `GET /api/workflow/{workflow_id}` - Get workflow status
- `GET /api/incident/{incident_id}` - Get incident details
- `GET /health` - Health check

**Azure Functions:**

- `POST /api/remediation` - Execute remediation action
- `GET /health` - Health check

## 🤝 Contributing

This is a reference implementation. To adapt for your organization:

1. Customize agent instructions for your environment
2. Add your specific remediation actions to Azure Functions
3. Populate knowledge base with your runbooks
4. Configure ServiceNow webhook integration
5. Adjust approval workflows as needed

## 📝 License

MIT License - See LICENSE file

## 🙋 Support

For issues or questions:

1. Check troubleshooting section above
2. Review Application Insights logs
3. Consult Microsoft Agent Framework documentation
4. Open an issue with detailed logs

---

**⚠️ Important Notes:**

- **--pre flag required**: Agent Framework is in preview
- **AAD authentication only**: No keys or connection strings for Cosmos DB
- **Managed Identity**: Use managed identity in production Azure environments
- **Human approval**: Always required before remediation execution
- **Test thoroughly**: Test in non-production environment first

---

**Built with:**
- Microsoft Agent Framework (Python)
- Azure AI Foundry
- Azure Cosmos DB
- Azure AI Search
- Azure Communication Services
- Azure Functions
- FastAPI
