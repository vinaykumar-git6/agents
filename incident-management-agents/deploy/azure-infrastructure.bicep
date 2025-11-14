// Azure Infrastructure for Incident Management Agent System
// Deploy with: az deployment group create --resource-group <rg-name> --template-file deploy.bicep

@description('Location for all resources')
param location string = resourceGroup().location

@description('Unique suffix for resource names')
param uniqueSuffix string = uniqueString(resourceGroup().id)

@description('Azure AI Foundry project endpoint')
param aiProjectEndpoint string

@description('AI model deployment name')
param aiModelDeploymentName string

@description('Approver email addresses (comma-separated)')
param approverEmails string

// ============================================================
// Cosmos DB Account
// ============================================================
resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: 'cosmos-incident-${uniqueSuffix}'
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    disableLocalAuth: true  // AAD authentication only
    disableKeyBasedMetadataWriteAccess: true
  }
}

// Cosmos DB Database
resource cosmosDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmosAccount
  name: 'IncidentManagementDB'
  properties: {
    resource: {
      id: 'IncidentManagementDB'
    }
  }
}

// Containers
resource incidentsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: cosmosDatabase
  name: 'Incidents'
  properties: {
    resource: {
      id: 'Incidents'
      partitionKey: {
        paths: ['/incident_id']
        kind: 'Hash'
      }
    }
  }
}

resource workflowStateContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: cosmosDatabase
  name: 'WorkflowStates'
  properties: {
    resource: {
      id: 'WorkflowStates'
      partitionKey: {
        paths: ['/workflow_id']
        kind: 'Hash'
      }
    }
  }
}

resource approvalsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: cosmosDatabase
  name: 'Approvals'
  properties: {
    resource: {
      id: 'Approvals'
      partitionKey: {
        paths: ['/approval_id']
        kind: 'Hash'
      }
    }
  }
}

// ============================================================
// Azure AI Search Service
// ============================================================
resource searchService 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: 'search-incident-${uniqueSuffix}'
  location: location
  sku: {
    name: 'basic'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    disableLocalAuth: false  // Search needs key or AAD
  }
}

// ============================================================
// Azure Communication Services
// ============================================================
resource communicationService 'Microsoft.Communication/communicationServices@2023-04-01' = {
  name: 'acs-incident-${uniqueSuffix}'
  location: 'global'
  properties: {
    dataLocation: 'United States'
  }
}

resource emailService 'Microsoft.Communication/emailServices@2023-04-01' = {
  name: 'email-incident-${uniqueSuffix}'
  location: 'global'
  properties: {
    dataLocation: 'United States'
  }
}

resource emailDomain 'Microsoft.Communication/emailServices/domains@2023-04-01' = {
  parent: emailService
  name: 'AzureManagedDomain'
  location: 'global'
  properties: {
    domainManagement: 'AzureManaged'
    userEngagementTracking: 'Disabled'
  }
}

// ============================================================
// Application Insights
// ============================================================
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'logs-incident-${uniqueSuffix}'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-incident-${uniqueSuffix}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// ============================================================
// Storage Account (for Function App)
// ============================================================
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stincident${uniqueSuffix}'
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
  }
}

// ============================================================
// App Service Plan
// ============================================================
resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: 'plan-incident-${uniqueSuffix}'
  location: location
  sku: {
    name: 'P1v2'
    tier: 'PremiumV2'
  }
  properties: {
    reserved: true  // Linux
  }
  kind: 'linux'
}

// ============================================================
// Function App (Remediation Actions)
// ============================================================
resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: 'func-remediation-${uniqueSuffix}'
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      appSettings: [
        {
          name: 'AzureWebJobsStorage'
          value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'
        }
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsights.properties.ConnectionString
        }
        {
          name: 'AZURE_SUBSCRIPTION_ID'
          value: subscription().subscriptionId
        }
      ]
    }
  }
}

// ============================================================
// Web App (Webhook Server)
// ============================================================
resource webhookApp 'Microsoft.Web/sites@2023-12-01' = {
  name: 'app-webhook-${uniqueSuffix}'
  location: location
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      appSettings: [
        {
          name: 'AZURE_AI_PROJECT_ENDPOINT'
          value: aiProjectEndpoint
        }
        {
          name: 'AZURE_AI_MODEL_DEPLOYMENT_NAME'
          value: aiModelDeploymentName
        }
        {
          name: 'COSMOS_ENDPOINT'
          value: cosmosAccount.properties.documentEndpoint
        }
        {
          name: 'COSMOS_DATABASE_NAME'
          value: 'IncidentManagementDB'
        }
        {
          name: 'COSMOS_INCIDENTS_CONTAINER'
          value: 'Incidents'
        }
        {
          name: 'COSMOS_WORKFLOW_STATE_CONTAINER'
          value: 'WorkflowStates'
        }
        {
          name: 'COSMOS_APPROVALS_CONTAINER'
          value: 'Approvals'
        }
        {
          name: 'AZURE_SEARCH_ENDPOINT'
          value: 'https://${searchService.name}.search.windows.net'
        }
        {
          name: 'AZURE_SEARCH_INDEX_NAME'
          value: 'remediation-knowledge-base'
        }
        {
          name: 'AZURE_COMMUNICATION_CONNECTION_STRING'
          value: 'endpoint=https://${communicationService.name}.communication.azure.com/;accesskey=${communicationService.listKeys().primaryKey}'
        }
        {
          name: 'AZURE_COMMUNICATION_SENDER_EMAIL'
          value: 'DoNotReply@${emailDomain.properties.mailFromSenderDomain}'
        }
        {
          name: 'AZURE_FUNCTIONS_REMEDIATION_URL'
          value: 'https://${functionApp.properties.defaultHostName}'
        }
        {
          name: 'APPROVAL_REQUIRED_EMAILS'
          value: approverEmails
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsights.properties.ConnectionString
        }
      ]
    }
  }
}

// ============================================================
// RBAC Role Assignments
// ============================================================

// Cosmos DB Data Contributor for Webhook App
resource webhookCosmosRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmosAccount
  name: guid(cosmosAccount.id, webhookApp.id, 'contributor')
  properties: {
    roleDefinitionId: '${cosmosAccount.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'  // Built-in Data Contributor
    principalId: webhookApp.identity.principalId
    scope: cosmosAccount.id
  }
}

// Contributor role for Function App (to manage resources)
resource functionContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(functionApp.id, 'contributor')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b24988ac-6180-42a0-ab88-20f7382dd24c')  // Contributor
    principalId: functionApp.identity.principalId
  }
}

// ============================================================
// Outputs
// ============================================================
output cosmosEndpoint string = cosmosAccount.properties.documentEndpoint
output searchEndpoint string = 'https://${searchService.name}.search.windows.net'
output searchKey string = searchService.listAdminKeys().primaryKey
output webhookUrl string = 'https://${webhookApp.properties.defaultHostName}/webhook/servicenow/incident'
output functionAppUrl string = 'https://${functionApp.properties.defaultHostName}'
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output communicationConnectionString string = 'endpoint=https://${communicationService.name}.communication.azure.com/;accesskey=${communicationService.listKeys().primaryKey}'
output senderEmail string = 'DoNotReply@${emailDomain.properties.mailFromSenderDomain}'
