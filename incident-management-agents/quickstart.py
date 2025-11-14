"""
Quick Start Script for Incident Management Agent System
Run this to test the workflow locally.
"""
import asyncio
import logging
from workflow.incident_workflow import test_workflow

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

if __name__ == "__main__":
    print("=" * 80)
    print("Incident Management Agent System - Quick Start")
    print("=" * 80)
    print()
    print("This will test the complete workflow with a sample incident.")
    print()
    print("Prerequisites:")
    print("  ✓ .env file configured with Azure resource details")
    print("  ✓ Azure CLI authenticated (az login)")
    print("  ✓ Proper RBAC roles assigned")
    print()
    print("Starting workflow test...")
    print("=" * 80)
    print()
    
    try:
        asyncio.run(test_workflow())
        print()
        print("=" * 80)
        print("✅ Workflow test completed successfully!")
        print("=" * 80)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Test failed: {str(e)}")
        print("\nCheck the logs above for details.")
        print("Ensure all prerequisites are met and environment variables are configured.")
