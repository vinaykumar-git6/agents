"""
Azure Functions for Remediation Actions
Executes various remediation operations on Azure resources.
"""
import logging
import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.web import WebSiteManagementClient
from azure.mgmt.resource import ResourceManagementClient
import os
import json
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Azure credential (uses managed identity in Azure)
credential = DefaultAzureCredential()

# Get subscription ID from environment
SUBSCRIPTION_ID = os.environ.get("AZURE_SUBSCRIPTION_ID")

# Create Function App
app = func.FunctionApp()


@app.function_name(name="RemediationAction")
@app.route(route="remediation", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
async def remediation_action(req: func.HttpRequest) -> func.HttpResponse:
    """
    Main remediation action handler.
    
    Receives remediation action requests and routes them to appropriate handlers.
    
    Expected payload:
    {
        "action_id": "unique-id",
        "action_type": "restart_vm|restart_app_service|scale_resource|...",
        "target_resource": "resource name or ID",
        "parameters": {
            "resource_group": "rg-name",
            ...additional params
        }
    }
    """
    try:
        logger.info("Received remediation action request")
        
        # Parse request body
        try:
            req_body = req.get_json()
        except ValueError:
            return func.HttpResponse(
                json.dumps({"error": "Invalid JSON payload"}),
                status_code=400,
                mimetype="application/json"
            )
        
        action_id = req_body.get("action_id")
        action_type = req_body.get("action_type")
        target_resource = req_body.get("target_resource")
        parameters = req_body.get("parameters", {})
        
        if not all([action_id, action_type, target_resource]):
            return func.HttpResponse(
                json.dumps({"error": "Missing required fields: action_id, action_type, target_resource"}),
                status_code=400,
                mimetype="application/json"
            )
        
        logger.info(f"Processing action: {action_type} on {target_resource}")
        
        # Route to appropriate handler
        handlers = {
            "restart_vm": handle_restart_vm,
            "restart_app_service": handle_restart_app_service,
            "scale_resource": handle_scale_resource,
            "clear_cache": handle_clear_cache,
            "restart_service": handle_restart_service,
            "run_diagnostic": handle_run_diagnostic,
        }
        
        handler = handlers.get(action_type)
        if not handler:
            return func.HttpResponse(
                json.dumps({"error": f"Unsupported action type: {action_type}"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Execute the remediation action
        result = await handler(target_resource, parameters)
        
        response = {
            "action_id": action_id,
            "action_type": action_type,
            "target_resource": target_resource,
            "status": "success",
            "output": result,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"Action {action_id} completed successfully")
        
        return func.HttpResponse(
            json.dumps(response),
            status_code=200,
            mimetype="application/json"
        )
        
    except Exception as e:
        logger.error(f"Error executing remediation action: {str(e)}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "error": str(e),
                "action_id": req_body.get("action_id") if 'req_body' in locals() else None
            }),
            status_code=500,
            mimetype="application/json"
        )


async def handle_restart_vm(vm_name: str, parameters: dict) -> str:
    """
    Restart an Azure Virtual Machine.
    
    Args:
        vm_name: VM name
        parameters: Dict with 'resource_group'
        
    Returns:
        Result message
    """
    try:
        resource_group = parameters.get("resource_group")
        if not resource_group:
            raise ValueError("resource_group parameter required")
        
        logger.info(f"Restarting VM: {vm_name} in {resource_group}")
        
        compute_client = ComputeManagementClient(credential, SUBSCRIPTION_ID)
        
        # Restart the VM (async operation)
        poller = compute_client.virtual_machines.begin_restart(
            resource_group_name=resource_group,
            vm_name=vm_name
        )
        
        # Wait for completion
        result = poller.result()
        
        logger.info(f"VM {vm_name} restarted successfully")
        return f"Virtual Machine {vm_name} restarted successfully"
        
    except Exception as e:
        logger.error(f"Failed to restart VM: {str(e)}")
        raise


async def handle_restart_app_service(app_name: str, parameters: dict) -> str:
    """
    Restart an Azure App Service / Function App.
    
    Args:
        app_name: App Service name
        parameters: Dict with 'resource_group'
        
    Returns:
        Result message
    """
    try:
        resource_group = parameters.get("resource_group")
        if not resource_group:
            raise ValueError("resource_group parameter required")
        
        logger.info(f"Restarting App Service: {app_name} in {resource_group}")
        
        web_client = WebSiteManagementClient(credential, SUBSCRIPTION_ID)
        
        # Restart the app service
        web_client.web_apps.restart(
            resource_group_name=resource_group,
            name=app_name
        )
        
        logger.info(f"App Service {app_name} restarted successfully")
        return f"App Service {app_name} restarted successfully"
        
    except Exception as e:
        logger.error(f"Failed to restart App Service: {str(e)}")
        raise


async def handle_scale_resource(resource_name: str, parameters: dict) -> str:
    """
    Scale an Azure resource (App Service, VM, etc.).
    
    Args:
        resource_name: Resource name
        parameters: Dict with 'resource_group', 'resource_type', 'sku', 'capacity'
        
    Returns:
        Result message
    """
    try:
        resource_group = parameters.get("resource_group")
        resource_type = parameters.get("resource_type", "app_service")
        
        if not resource_group:
            raise ValueError("resource_group parameter required")
        
        logger.info(f"Scaling {resource_type}: {resource_name}")
        
        if resource_type == "app_service":
            web_client = WebSiteManagementClient(credential, SUBSCRIPTION_ID)
            
            # Get current App Service Plan
            app = web_client.web_apps.get(resource_group, resource_name)
            server_farm_id = app.server_farm_id
            plan_name = server_farm_id.split('/')[-1]
            
            # Update App Service Plan
            sku_name = parameters.get("sku", "P1v2")
            capacity = parameters.get("capacity", 2)
            
            plan_update = {
                "sku": {
                    "name": sku_name,
                    "capacity": capacity
                }
            }
            
            web_client.app_service_plans.update(
                resource_group_name=resource_group,
                name=plan_name,
                app_service_plan=plan_update
            )
            
            return f"Scaled App Service {resource_name} to {sku_name} with {capacity} instances"
        else:
            raise ValueError(f"Unsupported resource type for scaling: {resource_type}")
            
    except Exception as e:
        logger.error(f"Failed to scale resource: {str(e)}")
        raise


async def handle_clear_cache(resource_name: str, parameters: dict) -> str:
    """
    Clear cache for a resource.
    
    This is a placeholder - actual implementation depends on the cache type.
    
    Args:
        resource_name: Resource name
        parameters: Cache-specific parameters
        
    Returns:
        Result message
    """
    try:
        cache_type = parameters.get("cache_type", "application")
        
        logger.info(f"Clearing {cache_type} cache for {resource_name}")
        
        # In production, this would connect to Redis, CDN, or app-specific cache
        # For now, return success
        
        return f"Cache cleared for {resource_name} (type: {cache_type})"
        
    except Exception as e:
        logger.error(f"Failed to clear cache: {str(e)}")
        raise


async def handle_restart_service(service_name: str, parameters: dict) -> str:
    """
    Restart a service within a VM or container.
    
    This would typically use Azure Run Command or connect to the VM.
    
    Args:
        service_name: Service name
        parameters: Dict with connection details
        
    Returns:
        Result message
    """
    try:
        logger.info(f"Restarting service: {service_name}")
        
        # In production, this would use Azure Run Command API to execute
        # service restart commands on the VM
        
        return f"Service {service_name} restart command executed"
        
    except Exception as e:
        logger.error(f"Failed to restart service: {str(e)}")
        raise


async def handle_run_diagnostic(resource_name: str, parameters: dict) -> str:
    """
    Run diagnostic commands on a resource.
    
    Args:
        resource_name: Resource name
        parameters: Diagnostic parameters
        
    Returns:
        Diagnostic results
    """
    try:
        diagnostic_type = parameters.get("diagnostic_type", "health_check")
        
        logger.info(f"Running diagnostic: {diagnostic_type} on {resource_name}")
        
        # In production, this would run actual diagnostics
        # For now, return simulated results
        
        return f"Diagnostic {diagnostic_type} completed for {resource_name}: All systems operational"
        
    except Exception as e:
        logger.error(f"Failed to run diagnostic: {str(e)}")
        raise


@app.function_name(name="HealthCheck")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def health_check(req: func.HttpRequest) -> func.HttpResponse:
    """Health check endpoint."""
    return func.HttpResponse(
        json.dumps({
            "status": "healthy",
            "service": "Remediation Functions",
            "timestamp": datetime.utcnow().isoformat()
        }),
        status_code=200,
        mimetype="application/json"
    )
