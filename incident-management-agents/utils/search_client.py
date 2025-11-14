"""
Azure AI Search client for querying remediation knowledge base.
Uses Azure AD authentication with managed identity.
"""
import logging
from typing import Optional
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential
from config import config

logger = logging.getLogger(__name__)


class AzureSearchService:
    """Service for searching remediation knowledge base."""
    
    def __init__(self):
        """Initialize Azure AI Search client with AAD authentication."""
        self.credential = DefaultAzureCredential()
        
        # Azure AI Search supports both key and AAD authentication
        # Using AAD for better security
        self.search_client = SearchClient(
            endpoint=config.azure_search.endpoint,
            index_name=config.azure_search.index_name,
            credential=self.credential
        )
        
        logger.info("Azure AI Search service initialized successfully")
    
    def search_knowledge_base(
        self, 
        query: str, 
        top: int = 5,
        filters: Optional[str] = None
    ) -> list[dict]:
        """
        Search the knowledge base for relevant remediation procedures.
        
        Args:
            query: Search query text
            top: Number of results to return
            filters: OData filter expression
            
        Returns:
            List of search results with content and metadata
        """
        try:
            results = self.search_client.search(
                search_text=query,
                top=top,
                filter=filters,
                select=[
                    "id", 
                    "title", 
                    "content", 
                    "category", 
                    "symptoms",
                    "root_cause",
                    "remediation_steps",
                    "estimated_duration",
                    "risk_level",
                    "prerequisites",
                    "validation_steps"
                ],
                include_total_count=True
            )
            
            documents = []
            for result in results:
                doc = {
                    "id": result.get("id"),
                    "title": result.get("title"),
                    "content": result.get("content"),
                    "category": result.get("category"),
                    "symptoms": result.get("symptoms", []),
                    "root_cause": result.get("root_cause"),
                    "remediation_steps": result.get("remediation_steps", []),
                    "estimated_duration": result.get("estimated_duration"),
                    "risk_level": result.get("risk_level"),
                    "prerequisites": result.get("prerequisites", []),
                    "validation_steps": result.get("validation_steps", []),
                    "score": result.get("@search.score")
                }
                documents.append(doc)
            
            logger.info(f"Found {len(documents)} results for query: '{query}'")
            return documents
            
        except Exception as e:
            logger.error(f"Failed to search knowledge base: {str(e)}")
            raise
    
    def search_by_category(
        self, 
        category: str, 
        query: str, 
        top: int = 5
    ) -> list[dict]:
        """
        Search knowledge base filtered by category.
        
        Args:
            category: Category to filter (e.g., 'Infrastructure', 'Application')
            query: Search query text
            top: Number of results to return
            
        Returns:
            List of filtered search results
        """
        filter_expr = f"category eq '{category}'"
        return self.search_knowledge_base(query, top=top, filters=filter_expr)
    
    def get_document_by_id(self, doc_id: str) -> Optional[dict]:
        """
        Retrieve a specific knowledge base document by ID.
        
        Args:
            doc_id: Document identifier
            
        Returns:
            Document dictionary or None if not found
        """
        try:
            result = self.search_client.get_document(key=doc_id)
            logger.info(f"Retrieved document: {doc_id}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to retrieve document {doc_id}: {str(e)}")
            return None
    
    def search_similar_incidents(
        self, 
        symptoms: list[str], 
        affected_service: str,
        top: int = 3
    ) -> list[dict]:
        """
        Search for similar incidents based on symptoms and affected service.
        
        Args:
            symptoms: List of observed symptoms
            affected_service: Affected service or component
            top: Number of results to return
            
        Returns:
            List of similar incidents with remediation procedures
        """
        # Combine symptoms into a search query
        query = f"{affected_service} {' '.join(symptoms)}"
        
        results = self.search_knowledge_base(query, top=top)
        
        # Filter results that have high relevance
        relevant_results = [r for r in results if r.get("score", 0) > 1.0]
        
        logger.info(
            f"Found {len(relevant_results)} similar incidents for "
            f"service: {affected_service}"
        )
        return relevant_results
    
    def close(self):
        """Close search client connections."""
        self.search_client.close()
        logger.info("Azure AI Search service closed")


# Global Azure Search service instance
search_service = AzureSearchService()
