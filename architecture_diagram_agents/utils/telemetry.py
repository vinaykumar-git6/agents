"""
Telemetry configuration for Architecture Diagram Agents.
Provides OpenTelemetry tracing and Application Insights integration.
"""

import os
import logging
from typing import Optional
from contextlib import contextmanager

# Try to import OpenTelemetry packages with graceful fallback
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.resources import Resource
    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    OPENTELEMETRY_AVAILABLE = False
    logging.warning("OpenTelemetry packages not installed. Telemetry will be disabled.")

# Try to import Azure Monitor exporter with graceful fallback
try:
    from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
    AZURE_MONITOR_AVAILABLE = True
except ImportError:
    AZURE_MONITOR_AVAILABLE = False
    if OPENTELEMETRY_AVAILABLE:
        logging.warning("Azure Monitor OpenTelemetry exporter not installed. Telemetry will use basic tracing only.")

logger = logging.getLogger(__name__)

# Global tracer instance
_tracer = None
_tracer_provider = None


def initialize_telemetry(
    service_name: str = "architecture-diagram-agents",
    connection_string: Optional[str] = None,
    enabled: bool = True
) -> None:
    """
    Initialize OpenTelemetry with Azure Monitor integration.
    
    Args:
        service_name: Name of the service for telemetry
        connection_string: Application Insights connection string
        enabled: Whether telemetry is enabled
    """
    global _tracer, _tracer_provider
    
    if not enabled:
        logger.info("Telemetry disabled")
        return
    
    if not OPENTELEMETRY_AVAILABLE:
        logger.warning("OpenTelemetry packages not available. Telemetry disabled.")
        return
    
    try:
        # Get connection string from env if not provided
        conn_str = connection_string or os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
        
        if not conn_str:
            logger.warning("No Application Insights connection string found. Telemetry will not export to Azure Monitor.")
            return
        
        if not AZURE_MONITOR_AVAILABLE:
            logger.warning("Azure Monitor exporter not available. Basic telemetry only.")
            # Still initialize basic tracing without Azure Monitor
            _tracer_provider = TracerProvider()
            trace.set_tracer_provider(_tracer_provider)
            _tracer = trace.get_tracer(__name__)
            logger.info(f"Basic telemetry initialized for {service_name}")
            return
        
        # Create resource with service name
        resource = Resource.create({"service.name": service_name})
        
        # Create tracer provider
        _tracer_provider = TracerProvider(resource=resource)
        
        # Add console exporter for debugging
        console_exporter = ConsoleSpanExporter()
        console_processor = BatchSpanProcessor(console_exporter)
        _tracer_provider.add_span_processor(console_processor)
        
        # Add Azure Monitor exporter
        exporter = AzureMonitorTraceExporter(connection_string=conn_str)
        span_processor = BatchSpanProcessor(exporter)
        _tracer_provider.add_span_processor(span_processor)
        
        # Set as global tracer provider
        trace.set_tracer_provider(_tracer_provider)
        
        # Get tracer instance
        _tracer = trace.get_tracer(__name__)
        
        logger.info(f"Telemetry initialized for service: {service_name}")
        
    except Exception as e:
        logger.error(f"Failed to initialize telemetry: {e}")
        # Don't fail the application if telemetry fails


def get_tracer():
    """Get the global tracer instance."""
    global _tracer
    
    if not OPENTELEMETRY_AVAILABLE or _tracer is None:
        # Return None if telemetry not available
        return None
    
    return _tracer


@contextmanager
def trace_operation(
    operation_name: str,
    attributes: Optional[dict] = None
):
    """
    Context manager for tracing operations.
    
    Usage:
        with trace_operation("agent_execution", {"agent": "vision"}):
            # Your code here
            pass
    
    Args:
        operation_name: Name of the operation being traced
        attributes: Additional attributes to add to the span
    """
    if not OPENTELEMETRY_AVAILABLE:
        # No-op if telemetry not available
        yield
        return
    
    tracer = get_tracer()
    
    if tracer is None:
        # No-op if tracer not initialized
        yield
        return
    
    with tracer.start_as_current_span(operation_name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, str(value))
        
        try:
            yield span
        except Exception as e:
            span.set_attribute("error", True)
            span.set_attribute("error.message", str(e))
            span.set_attribute("error.type", type(e).__name__)
            raise


def add_event(event_name: str, attributes: Optional[dict] = None) -> None:
    """
    Add an event to the current span.
    
    Args:
        event_name: Name of the event
        attributes: Event attributes
    """
    if not OPENTELEMETRY_AVAILABLE:
        return
    
    try:
        current_span = trace.get_current_span()
        if current_span and current_span.is_recording():
            current_span.add_event(event_name, attributes or {})
    except Exception as e:
        logger.debug(f"Failed to add event: {e}")


def set_attribute(key: str, value) -> None:
    """
    Set an attribute on the current span.
    
    Args:
        key: Attribute key
        value: Attribute value
    """
    if not OPENTELEMETRY_AVAILABLE:
        return
    
    try:
        current_span = trace.get_current_span()
        if current_span and current_span.is_recording():
            current_span.set_attribute(key, str(value))
    except Exception as e:
        logger.debug(f"Failed to set attribute: {e}")


def shutdown_telemetry() -> None:
    """Shutdown telemetry and flush remaining data."""
    global _tracer_provider
    
    if not OPENTELEMETRY_AVAILABLE or not _tracer_provider:
        return
    
    try:
        _tracer_provider.shutdown()
        logger.info("Telemetry shutdown complete")
    except Exception as e:
        logger.error(f"Error shutting down telemetry: {e}")


# ============================================================================
# Enhanced Telemetry Manager for Comprehensive Observability
# ============================================================================

class NullSpan:
    """Null object pattern for spans when telemetry is not available."""
    
    def set_attribute(self, key: str, value) -> None:
        """No-op set_attribute"""
        pass
    
    def set_attributes(self, attributes: dict) -> None:
        """No-op set_attributes"""
        pass
    
    def add_event(self, name: str, attributes: dict = None) -> None:
        """No-op add_event"""
        pass
    
    def record_exception(self, exception: Exception) -> None:
        """No-op record_exception"""
        pass


class NullTracer:
    """Null object pattern for tracer when telemetry is not available."""
    
    @contextmanager
    def start_as_current_span(self, name: str):
        """No-op context manager that yields a NullSpan"""
        yield NullSpan()


class TelemetryManager:
    """Manages comprehensive observability with processing spans, business events, and metrics."""
    
    def __init__(self):
        self.tracer = get_tracer() or NullTracer()
    
    @contextmanager
    def create_processing_span(
        self,
        executor_id: str,
        executor_type: str,
        message_type: str
    ):
        """
        Create a processing span for an executor.
        
        Args:
            executor_id: Unique identifier for the executor
            executor_type: Type of executor (e.g., VisionAnalysis, ServiceAnalysis)
            message_type: Type of message being processed
        """
        if not OPENTELEMETRY_AVAILABLE:
            # Return a null-safe span wrapper
            yield NullSpan()
            return
        
        span_name = f"executor.process.{executor_id}"
        with self.tracer.start_as_current_span(span_name) as span:
            span.set_attributes({
                "executor.id": executor_id,
                "executor.type": executor_type,
                "message.type": message_type,
                "span.kind": "processing"
            })
            
            try:
                yield span
            except Exception as e:
                span.set_attribute("executor.success", False)
                span.set_attribute("executor.error", str(e))
                span.record_exception(e)
                raise
    
    @contextmanager
    def create_workflow_span(
        self,
        workflow_name: str,
        business_process: str = ""
    ):
        """
        Create a workflow-level span.
        
        Args:
            workflow_name: Name of the workflow
            business_process: Business process being executed
        """
        if not OPENTELEMETRY_AVAILABLE:
            # Return a null-safe span wrapper
            yield NullSpan()
            return
        
        with self.tracer.start_as_current_span(workflow_name) as span:
            span.set_attributes({
                "workflow.name": workflow_name,
                "workflow.type": "architecture_analysis",
                "span.kind": "workflow"
            })
            
            if business_process:
                span.set_attribute("business.process", business_process)
            
            try:
                yield span
            except Exception as e:
                span.set_attribute("workflow.success", False)
                span.set_attribute("workflow.error", str(e))
                span.record_exception(e)
                raise
    
    @contextmanager
    def create_detailed_operation_span(
        self,
        operation_name: str,
        category: str,
        **kwargs
    ):
        """
        Create a detailed operation span for sub-operations.
        
        Args:
            operation_name: Name of the operation
            category: Category of operation (e.g., business_metrics, ai_processing)
            **kwargs: Additional attributes
        """
        if not OPENTELEMETRY_AVAILABLE:
            # Return a null-safe span wrapper
            yield NullSpan()
            return
        
        span_name = f"operation.{category}.{operation_name}"
        with self.tracer.start_as_current_span(span_name) as span:
            span.set_attributes({
                "operation.name": operation_name,
                "operation.category": category,
                **{k: str(v) for k, v in kwargs.items()}
            })
            
            try:
                yield span
            except Exception as e:
                span.set_attribute("operation.success", False)
                span.set_attribute("operation.error", str(e))
                span.record_exception(e)
                raise
    
    def record_architecture_processed(self, step: str, job_id: str = "unknown"):
        """Record architecture processing metric."""
        if not OPENTELEMETRY_AVAILABLE:
            return
        
        try:
            current_span = trace.get_current_span()
            if current_span and current_span.is_recording():
                current_span.add_event("architecture.processed", {
                    "step": step,
                    "job_id": job_id
                })
        except Exception as e:
            logger.debug(f"Failed to record architecture metric: {e}")
    
    def record_vision_analysis(self, objects_count: int, tags_count: int, job_id: str = "unknown"):
        """Record vision analysis metric."""
        if not OPENTELEMETRY_AVAILABLE:
            return
        
        try:
            current_span = trace.get_current_span()
            if current_span and current_span.is_recording():
                current_span.add_event("vision.analysis.completed", {
                    "objects_count": objects_count,
                    "tags_count": tags_count,
                    "job_id": job_id
                })
        except Exception as e:
            logger.debug(f"Failed to record vision analysis metric: {e}")
    
    def record_service_analysis(self, services_count: int, job_id: str = "unknown"):
        """Record service analysis metric."""
        if not OPENTELEMETRY_AVAILABLE:
            return
        
        try:
            current_span = trace.get_current_span()
            if current_span and current_span.is_recording():
                current_span.add_event("service.analysis.completed", {
                    "services_count": services_count,
                    "job_id": job_id
                })
        except Exception as e:
            logger.debug(f"Failed to record service analysis metric: {e}")
    
    def record_best_practices(self, recommendations_count: int, job_id: str = "unknown"):
        """Record best practices metric."""
        if not OPENTELEMETRY_AVAILABLE:
            return
        
        try:
            current_span = trace.get_current_span()
            if current_span and current_span.is_recording():
                current_span.add_event("best_practices.generated", {
                    "recommendations_count": recommendations_count,
                    "job_id": job_id
                })
        except Exception as e:
            logger.debug(f"Failed to record best practices metric: {e}")
    
    def record_terraform_generation(self, files_count: int, job_id: str = "unknown"):
        """Record Terraform generation metric."""
        if not OPENTELEMETRY_AVAILABLE:
            return
        
        try:
            current_span = trace.get_current_span()
            if current_span and current_span.is_recording():
                current_span.add_event("terraform.generated", {
                    "files_count": files_count,
                    "job_id": job_id
                })
        except Exception as e:
            logger.debug(f"Failed to record Terraform metric: {e}")


def send_business_event(event_name: str, attributes: dict):
    """
    Send a business event with attributes.
    
    Args:
        event_name: Name of the business event
        attributes: Event attributes
    """
    if not OPENTELEMETRY_AVAILABLE:
        return
    
    try:
        current_span = trace.get_current_span()
        if current_span and current_span.is_recording():
            # Convert all values to strings for OpenTelemetry
            str_attributes = {k: str(v) for k, v in attributes.items()}
            current_span.add_event(event_name, str_attributes)
            logger.debug(f"Business event: {event_name} - {attributes}")
    except Exception as e:
        logger.debug(f"Failed to send business event: {e}")


def get_telemetry_manager() -> TelemetryManager:
    """Get the global telemetry manager instance."""
    return TelemetryManager()


def flush_telemetry():
    """Flush telemetry data (alias for shutdown_telemetry for compatibility)."""
    shutdown_telemetry()


def get_current_trace_id() -> Optional[str]:
    """Get the current trace ID."""
    if not OPENTELEMETRY_AVAILABLE:
        return None
    
    try:
        current_span = trace.get_current_span()
        if current_span and current_span.is_recording():
            trace_id = current_span.get_span_context().trace_id
            return format(trace_id, '032x')
    except Exception:
        pass
    
    return None