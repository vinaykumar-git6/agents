"""
Architecture Diagram Analyzer
A Python package for analyzing architecture diagrams using Azure Computer Vision
and AI agents to identify cloud services and generate Infrastructure as Code.
"""

__version__ = "2.1.0"
__author__ = "Your Organization"

# Core models and utilities
from .core import Config, AnalysisResult, VisionAnalysisResult, AgentAnalysisResult
from .utils import setup_logging, get_logger

# Agentic architecture - all agents in agents folder (optional, may fail on some architectures)
try:
    from .agents import (
        VisionAgent,
        AnalyzerAgent,
        AzureBestPracticeAgent,
        IACGeneratorAgent,
    )
    from .workflows.orchestrator import WorkflowOrchestrator
    AGENTS_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Agent framework not available: {e}")
    print("The app will run in legacy mode without AI agents.")
    AGENTS_AVAILABLE = False
    # Provide dummy classes for compatibility
    VisionAgent = None
    AnalyzerAgent = None
    AzureBestPracticeAgent = None
    IACGeneratorAgent = None
    WorkflowOrchestrator = None

__all__ = [
    # Agents
    "VisionAgent",
    "AnalyzerAgent",
    "AzureBestPracticeAgent",
    "IACGeneratorAgent",
    # Core
    "Config",
    "AnalysisResult",
    "VisionAnalysisResult",
    "AgentAnalysisResult",
    # Utilities
    "setup_logging",
    "get_logger",
    # Orchestration
    "WorkflowOrchestrator",
]
