"""
Azure Cosmos DB client for storing incident data and workflow state.
Uses Azure AD authentication with managed identity (no keys).
"""
import logging
from typing import Optional, Any
from datetime import datetime
from azure.cosmos import CosmosClient, exceptions, PartitionKey
from azure.identity import DefaultAzureCredential
from config import config

logger = logging.getLogger(__name__)


class CosmosDBService:
    """Service for interacting with Azure Cosmos DB."""
    
    def __init__(self):
        """Initialize Cosmos DB client with AAD authentication."""
        self.credential = DefaultAzureCredential()
        self.client = CosmosClient(
            config.cosmos_db.endpoint,
            credential=self.credential
        )
        self.database = self.client.get_database_client(config.cosmos_db.database_name)
        
        # Container clients
        self.incidents_container = self.database.get_container_client(
            config.cosmos_db.incidents_container
        )
        self.workflow_state_container = self.database.get_container_client(
            config.cosmos_db.workflow_state_container
        )
        self.approvals_container = self.database.get_container_client(
            config.cosmos_db.approvals_container
        )
        
        logger.info("Cosmos DB service initialized successfully")
    
    async def create_database_and_containers(self):
        """
        Create database and containers if they don't exist.
        Only needed for initial setup.
        """
        try:
            # Create database
            database = await self.client.create_database_if_not_exists(
                id=config.cosmos_db.database_name
            )
            logger.info(f"Database '{config.cosmos_db.database_name}' ready")
            
            # Create containers with partition keys
            containers = [
                (config.cosmos_db.incidents_container, "/incident_id"),
                (config.cosmos_db.workflow_state_container, "/workflow_id"),
                (config.cosmos_db.approvals_container, "/approval_id"),
            ]
            
            for container_name, partition_key_path in containers:
                await database.create_container_if_not_exists(
                    id=container_name,
                    partition_key=PartitionKey(path=partition_key_path),
                )
                logger.info(f"Container '{container_name}' ready")
                
        except exceptions.CosmosHttpResponseError as e:
            logger.error(f"Failed to create database/containers: {e.message}")
            raise
    
    def save_workflow_state(self, workflow_state: dict[str, Any]) -> dict[str, Any]:
        """
        Save or update workflow state.
        
        Args:
            workflow_state: Workflow state dictionary
            
        Returns:
            Saved workflow state with Cosmos DB metadata
        """
        try:
            workflow_state["updated_at"] = datetime.utcnow().isoformat()
            workflow_state["id"] = workflow_state.get("workflow_id")
            
            result = self.workflow_state_container.upsert_item(workflow_state)
            logger.info(f"Saved workflow state: {workflow_state['workflow_id']}")
            return result
            
        except exceptions.CosmosHttpResponseError as e:
            logger.error(f"Failed to save workflow state: {e.message}")
            raise
    
    def get_workflow_state(self, workflow_id: str) -> Optional[dict[str, Any]]:
        """
        Retrieve workflow state by ID.
        
        Args:
            workflow_id: Unique workflow identifier
            
        Returns:
            Workflow state dictionary or None if not found
        """
        try:
            return self.workflow_state_container.read_item(
                item=workflow_id,
                partition_key=workflow_id
            )
        except exceptions.CosmosResourceNotFoundError:
            logger.warning(f"Workflow state not found: {workflow_id}")
            return None
        except exceptions.CosmosHttpResponseError as e:
            logger.error(f"Failed to retrieve workflow state: {e.message}")
            raise
    
    def save_incident(self, incident: dict[str, Any]) -> dict[str, Any]:
        """
        Save incident data.
        
        Args:
            incident: Incident dictionary
            
        Returns:
            Saved incident with Cosmos DB metadata
        """
        try:
            incident["id"] = incident.get("sys_id") or incident.get("incident_id")
            result = self.incidents_container.upsert_item(incident)
            logger.info(f"Saved incident: {incident['id']}")
            return result
            
        except exceptions.CosmosHttpResponseError as e:
            logger.error(f"Failed to save incident: {e.message}")
            raise
    
    def get_incident(self, incident_id: str) -> Optional[dict[str, Any]]:
        """
        Retrieve incident by ID.
        
        Args:
            incident_id: Incident identifier
            
        Returns:
            Incident dictionary or None if not found
        """
        try:
            return self.incidents_container.read_item(
                item=incident_id,
                partition_key=incident_id
            )
        except exceptions.CosmosResourceNotFoundError:
            logger.warning(f"Incident not found: {incident_id}")
            return None
        except exceptions.CosmosHttpResponseError as e:
            logger.error(f"Failed to retrieve incident: {e.message}")
            raise
    
    def save_approval_request(self, approval: dict[str, Any]) -> dict[str, Any]:
        """
        Save approval request.
        
        Args:
            approval: Approval request dictionary
            
        Returns:
            Saved approval with Cosmos DB metadata
        """
        try:
            approval["id"] = approval.get("approval_id")
            result = self.approvals_container.upsert_item(approval)
            logger.info(f"Saved approval request: {approval['id']}")
            return result
            
        except exceptions.CosmosHttpResponseError as e:
            logger.error(f"Failed to save approval request: {e.message}")
            raise
    
    def get_approval_request(self, approval_id: str) -> Optional[dict[str, Any]]:
        """
        Retrieve approval request by ID.
        
        Args:
            approval_id: Approval identifier
            
        Returns:
            Approval dictionary or None if not found
        """
        try:
            return self.approvals_container.read_item(
                item=approval_id,
                partition_key=approval_id
            )
        except exceptions.CosmosResourceNotFoundError:
            logger.warning(f"Approval request not found: {approval_id}")
            return None
        except exceptions.CosmosHttpResponseError as e:
            logger.error(f"Failed to retrieve approval request: {e.message}")
            raise
    
    def update_approval_status(
        self, 
        approval_id: str, 
        status: str,
        approved_by: Optional[str] = None,
        rejection_reason: Optional[str] = None
    ) -> dict[str, Any]:
        """
        Update approval request status.
        
        Args:
            approval_id: Approval identifier
            status: New status
            approved_by: Email of approver
            rejection_reason: Reason for rejection
            
        Returns:
            Updated approval dictionary
        """
        try:
            approval = self.get_approval_request(approval_id)
            if not approval:
                raise ValueError(f"Approval request not found: {approval_id}")
            
            approval["status"] = status
            if approved_by:
                approval["approved_by"] = approved_by
                approval["approved_at"] = datetime.utcnow().isoformat()
            if rejection_reason:
                approval["rejection_reason"] = rejection_reason
            
            return self.save_approval_request(approval)
            
        except exceptions.CosmosHttpResponseError as e:
            logger.error(f"Failed to update approval status: {e.message}")
            raise
    
    def close(self):
        """Close Cosmos DB client connections."""
        # Cosmos client doesn't require explicit cleanup in current SDK
        logger.info("Cosmos DB service closed")


# Global Cosmos DB service instance
cosmos_service = CosmosDBService()
