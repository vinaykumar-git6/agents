# Deployment Guide - Incident Management Agent System

## Prerequisites

- Azure subscription with Owner or Contributor + User Access Administrator roles
- Azure CLI installed and authenticated
- PowerShell 7+ (for Windows)
- Python 3.11+

## Step 1: Deploy Azure Infrastructure

```powershell
# Set variables
$resourceGroup = "rg-incident-management"
$location = "eastus"
$aiProjectEndpoint = "https://your-ai-project.cognitiveservices.azure.com/"
$aiModelDeployment = "gpt-4o-mini"
$approverEmails = "admin1@company.com,admin2@company.com"

# Create resource group
az group create --name $resourceGroup --location $location

# Deploy infrastructure
az deployment group create `
    --resource-group $resourceGroup `
    --template-file deploy/azure-infrastructure.bicep `
    --parameters `
        aiProjectEndpoint=$aiProjectEndpoint `
        aiModelDeploymentName=$aiModelDeployment `
        approverEmails=$approverEmails

# Get outputs
$deployment = az deployment group show `
    --resource-group $resourceGroup `
    --name azure-infrastructure `
    --query properties.outputs `
    --output json | ConvertFrom-Json

$cosmosEndpoint = $deployment.cosmosEndpoint.value
$searchEndpoint = $deployment.searchEndpoint.value
$webhookUrl = $deployment.webhookUrl.value
$functionAppName = $deployment.functionAppUrl.value.Split("//")[1].Split(".")[0]
$webhookAppName = $webhookUrl.Split("//")[1].Split(".")[0]
```

## Step 2: Populate Knowledge Base

```powershell
# Create sample knowledge base entries
az search index create `
    --service-name $searchServiceName `
    --name remediation-knowledge-base `
    --fields @knowledge-base-schema.json

# Upload documents (create your KB documents in JSON format)
az search index data upload `
    --service-name $searchServiceName `
    --index-name remediation-knowledge-base `
    --documents @knowledge-base-data.json
```

**Sample Knowledge Base Entry:**

```json
{
  "id": "KB001",
  "title": "Application Server Not Responding",
  "category": "Infrastructure",
  "symptoms": ["timeout errors", "server unresponsive", "high memory usage"],
  "root_cause": "Memory leak in application causing OutOfMemory errors",
  "remediation_steps": [
    "Restart the application service",
    "Clear application cache",
    "Monitor memory usage",
    "Review application logs for memory leaks"
  ],
  "estimated_duration": 10,
  "risk_level": "MEDIUM",
  "prerequisites": ["Verify no active user sessions", "Create backup"],
  "validation_steps": ["Check service status", "Verify application responds", "Monitor memory usage"]
}
```

## Step 3: Deploy Function App

```powershell
# Navigate to functions directory
cd azure_functions

# Install Azure Functions Core Tools if not installed
# https://learn.microsoft.com/azure/azure-functions/functions-run-local

# Publish functions
func azure functionapp publish $functionAppName --python

# Verify deployment
func azure functionapp list-functions $functionAppName
```

## Step 4: Deploy Webhook App

```powershell
# Navigate to project root
cd ..

# Create deployment package
# Install dependencies
pip install --target=".python_packages/lib/site-packages" -r requirements.txt

# Create zip (exclude venv, tests, etc.)
$files = @(
    "agents",
    "config",
    "models",
    "utils",
    "workflow",
    "webhook_server.py",
    ".python_packages"
)

Compress-Archive -Path $files -DestinationPath deploy.zip -Force

# Deploy to Azure
az webapp deployment source config-zip `
    --resource-group $resourceGroup `
    --name $webhookAppName `
    --src deploy.zip

# Set startup command
az webapp config set `
    --resource-group $resourceGroup `
    --name $webhookAppName `
    --startup-file "python -m uvicorn webhook_server:app --host 0.0.0.0 --port 8000"

# Restart app
az webapp restart --resource-group $resourceGroup --name $webhookAppName
```

## Step 5: Configure ServiceNow Webhook

1. **In ServiceNow, navigate to:** System Web Services > Outbound > REST Message

2. **Create new REST Message:**
   - Name: "Incident Management Agent Webhook"
   - Endpoint: `<webhook-url-from-deployment>`
   - HTTP Method: POST
   - Authentication: None (use signature)

3. **Add HTTP Header:**
   - Name: `X-ServiceNow-Signature`
   - Value: `${webhook_signature}`

4. **Create Business Rule:**
   - Table: Incident
   - When: After Insert or Update
   - Conditions: Priority is 1 or 2
   - Action: Send REST message with incident data

**Sample Business Rule Script:**

```javascript
(function executeRule(current, previous /*null when async*/) {
    try {
        var r = new sn_ws.RESTMessageV2('Incident Management Agent Webhook', 'Default POST');
        
        var incidentData = {
            sys_id: current.sys_id.toString(),
            number: current.number.toString(),
            short_description: current.short_description.toString(),
            description: current.description.toString(),
            priority: current.priority.toString(),
            urgency: current.urgency.toString(),
            impact: current.impact.toString(),
            category: current.category.toString(),
            subcategory: current.subcategory.toString(),
            configuration_item: current.cmdb_ci.toString(),
            state: current.state.toString(),
            opened_at: current.opened_at.toString(),
            assigned_to: current.assigned_to.getDisplayValue(),
            additional_comments: current.comments.toString()
        };
        
        r.setStringParameterNoEscape('body', JSON.stringify(incidentData));
        
        var response = r.execute();
        var httpStatus = response.getStatusCode();
        
        gs.info('Incident webhook sent: ' + httpStatus);
        
    } catch(ex) {
        gs.error('Error sending incident webhook: ' + ex.message);
    }
})(current, previous);
```

## Step 6: Verify Deployment

```powershell
# Test webhook endpoint
$testIncident = @{
    sys_id = "test_" + (New-Guid).ToString()
    number = "INC0012345"
    short_description = "Test incident"
    description = "Test incident for validation"
    priority = "3"
    urgency = "3"
    impact = "3"
    category = "Infrastructure"
    subcategory = "Server"
    configuration_item = "TEST-SERVER-01"
    state = "2"
    opened_at = (Get-Date).ToString("o")
} | ConvertTo-Json

Invoke-WebRequest `
    -Uri "$webhookUrl" `
    -Method POST `
    -Body $testIncident `
    -ContentType "application/json" `
    -Verbose

# Check logs in Application Insights
az monitor app-insights query `
    --app $appInsightsName `
    --analytics-query "traces | where message contains 'workflow' | order by timestamp desc | take 20"

# Check Cosmos DB for workflow state
# Use Azure Portal or Azure CLI to query Cosmos DB
```

## Step 7: Monitor the System

### Application Insights Queries

**Workflow Executions:**
```kusto
traces
| where message contains "workflow"
| project timestamp, message, severityLevel
| order by timestamp desc
```

**Agent Performance:**
```kusto
customEvents
| where name startswith "agent_"
| summarize count(), avg(duration) by name
| order by count_ desc
```

**Failures:**
```kusto
exceptions
| order by timestamp desc
| take 50
```

### Cosmos DB Queries

**Active Workflows:**
```sql
SELECT * FROM c 
WHERE c.current_status IN ("analyzing", "planning", "pending_approval", "remediating")
ORDER BY c.created_at DESC
```

**Pending Approvals:**
```sql
SELECT * FROM c
WHERE c.status = "pending" 
  AND c.expires_at > GetCurrentDateTime()
```

## Step 8: Configure Alerts

```powershell
# Create alert for failed workflows
az monitor metrics alert create `
    --name "Workflow Failures" `
    --resource-group $resourceGroup `
    --scopes $appInsightsResourceId `
    --condition "count exceptions > 5" `
    --window-size 5m `
    --evaluation-frequency 1m `
    --action-groups $actionGroupId

# Create alert for pending approvals
az monitor metrics alert create `
    --name "Stale Approvals" `
    --resource-group $resourceGroup `
    --scopes $cosmosResourceId `
    --condition "count requests where status=pending > 10" `
    --window-size 30m
```

## Troubleshooting

### Webhook Not Receiving Requests

1. Check ServiceNow Business Rule is active
2. Verify webhook URL is correct
3. Check App Service logs: `az webapp log tail --name $webhookAppName --resource-group $resourceGroup`
4. Verify network connectivity

### Agents Not Running

1. Check managed identity has proper RBAC roles
2. Verify AI Foundry endpoint and model deployment
3. Check Application Insights for errors
4. Verify all environment variables are set correctly

### Remediation Actions Failing

1. Check Function App logs
2. Verify managed identity has Contributor role
3. Test Azure Functions locally first
4. Verify target resources exist and are accessible

### Approval Emails Not Sending

1. Verify Azure Communication Services is configured
2. Check email domain is verified
3. Review ACS service quotas
4. Test email sending separately

## Security Checklist

- [ ] All resources use managed identity (no keys)
- [ ] Cosmos DB has `disableLocalAuth: true`
- [ ] Webhook has signature verification enabled
- [ ] Function App uses HTTPS only
- [ ] Application Insights enabled for all components
- [ ] RBAC roles follow least privilege principle
- [ ] Secrets stored in Key Vault (not in code)
- [ ] Network security groups configured (if needed)
- [ ] Regular security audits scheduled

## Cost Optimization

- Start with Basic tier for Search service
- Use consumption plan for Function App if low volume
- Enable Cosmos DB autoscale for variable workloads
- Set appropriate retention for Application Insights logs
- Monitor and optimize AI model token usage

## Next Steps

1. Add more remediation actions to Azure Functions
2. Expand knowledge base with your runbooks
3. Customize agent instructions for your environment
4. Set up proper CI/CD pipelines
5. Implement additional approval workflows as needed
6. Create dashboards in Azure Monitor

---

**For production deployments:**
- Use separate environments (dev, staging, prod)
- Implement proper CI/CD with testing
- Set up disaster recovery and backup strategies
- Configure custom domains and SSL certificates
- Implement rate limiting and throttling
- Add comprehensive monitoring and alerting
