"""
Quick Start Script for ArchDiag IaC Agents

Simple script to test the workflow with a sample diagram.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


async def main():
    """Run a quick test of the workflow."""
    print("=" * 80)
    print("ArchDiag IaC Agents - Quick Start")
    print("=" * 80)
    print()

    # Check if sample diagram exists
    sample_diagram = Path("samples/architecture-diagram.png")

    if not sample_diagram.exists():
        print("❌ Sample diagram not found!")
        print(f"Expected location: {sample_diagram.absolute()}")
        print()
        print("To test the workflow:")
        print("1. Create a 'samples' directory")
        print("2. Add an architecture diagram image (PNG, JPEG, etc.)")
        print("3. Run this script again")
        print()
        print("Or provide your own diagram path:")
        print("  python quickstart.py /path/to/your/diagram.png")
        return

    # Get diagram path from args or use sample
    if len(sys.argv) > 1:
        diagram_path = Path(sys.argv[1])
        if not diagram_path.exists():
            print(f"❌ Diagram not found: {diagram_path}")
            return
    else:
        diagram_path = sample_diagram

    print(f"📊 Using diagram: {diagram_path.name}")
    print()

    try:
        # Import workflow
        from workflow import run_workflow

        print("🚀 Starting workflow...")
        print()

        # Run workflow
        result = await run_workflow(
            image_path=diagram_path,
            resource_group="rg-quickstart-test",
            location="eastus",
        )

        # Display results
        print()
        print("=" * 80)
        print("✅ Workflow Completed!")
        print("=" * 80)
        print()
        print(f"Workflow ID: {result.workflow_id}")
        print(f"Final Stage: {result.current_stage.value}")
        print(f"Has Errors: {result.has_errors}")
        print()

        # Stage 1: Diagram Analysis
        if result.diagram_analysis:
            print("📊 Stage 1: Diagram Analysis")
            print(f"  - Resources Detected: {len(result.diagram_analysis.resources)}")
            print(f"  - Confidence: {result.diagram_analysis.overall_confidence:.2f}")
            print(f"  - Text Lines: {len(result.diagram_analysis.detected_text)}")
            print()

        # Stage 2: Resource Specification
        if result.resource_specification:
            print("🔍 Stage 2: Resource Specification")
            print(f"  - Total Resources: {result.resource_specification.total_resources}")
            print(f"  - Default Location: {result.resource_specification.default_location}")
            print(f"  - Resource Group: {result.resource_specification.default_resource_group}")
            if result.resource_specification.resource_types_summary:
                print("  - Resource Types:")
                for rtype, count in result.resource_specification.resource_types_summary.items():
                    print(f"    • {rtype}: {count}")
            print()

        # Stage 3: Bicep Code
        if result.bicep_code:
            print("📝 Stage 3: Bicep Code Generation")
            print(f"  - Resources: {len(result.bicep_code.resources)}")
            print(f"  - Parameters: {len(result.bicep_code.parameters)}")
            print(f"  - Outputs: {len(result.bicep_code.outputs)}")
            print(f"  - Code Length: {len(result.bicep_code.bicep_code)} characters")
            
            # Save Bicep code
            output_file = Path(f"output-{result.workflow_id}.bicep")
            output_file.write_text(result.bicep_code.bicep_code)
            print(f"  - Saved to: {output_file.name}")
            print()

        # Stage 4: Validation
        if result.validation_result:
            print("✅ Stage 4: IaC Review")
            print(f"  - Is Valid: {result.validation_result.is_valid}")
            print(f"  - Syntax Valid: {result.validation_result.syntax_valid}")
            print(f"  - Security Check: {'✓' if result.validation_result.security_check_passed else '✗'}")
            print(f"  - Best Practices: {'✓' if result.validation_result.best_practices_passed else '✗'}")
            print(f"  - Total Issues: {len(result.validation_result.issues)}")
            if result.validation_result.issue_summary:
                print("  - Issue Breakdown:")
                for severity, count in result.validation_result.issue_summary.items():
                    if count > 0:
                        print(f"    • {severity.upper()}: {count}")
            print()

        # Stage 5: Correction
        if result.corrected_bicep_code:
            print("🔧 Stage 5: IaC Correction")
            print(f"  - Auto-fix Success: {'✓' if result.corrected_bicep_code.auto_fix_success else '✗'}")
            print(f"  - Corrections Applied: {len(result.corrected_bicep_code.corrections_applied)}")
            print(f"  - Original Issues: {result.corrected_bicep_code.original_issues_count}")
            print(f"  - Remaining Issues: {result.corrected_bicep_code.remaining_issues_count}")
            
            # Save corrected Bicep code
            corrected_output_file = Path(f"output-{result.workflow_id}-corrected.bicep")
            corrected_output_file.write_text(result.corrected_bicep_code.bicep_code)
            print(f"  - Corrected Code Saved: {corrected_output_file.name}")
            print()

        # Stage 6: Deployment
        if result.deployment_result:
            print("🚀 Stage 6: Deployment")
            print(f"  - Status: {result.deployment_result.status.value}")
            print(f"  - Deployment ID: {result.deployment_result.deployment_id}")
            print(f"  - Total Resources: {result.deployment_result.total_resources}")
            print(f"  - Successful: {result.deployment_result.successful_resources}")
            if result.deployment_result.error_message:
                print(f"  - Error: {result.deployment_result.error_message}")
            print()

        # Summary
        print("=" * 80)
        print("Next Steps:")
        print("=" * 80)
        if result.bicep_code:
            print(f"1. Review original Bicep: output-{result.workflow_id}.bicep")
            if result.corrected_bicep_code:
                print(f"2. Review corrected Bicep: output-{result.workflow_id}-corrected.bicep")
                print("3. Compare original vs corrected to see auto-fixes")
                print("4. Deploy corrected code: az deployment group create ...")
            else:
                print("2. Validate manually: az bicep build --file output-{workflow_id}.bicep")
                print("3. Deploy to Azure: az deployment group create ...")
        print("5. Start API server: python api_server.py")
        print("6. Upload more diagrams via API")
        print()

    except ImportError as e:
        print(f"❌ Import Error: {e}")
        print()
        print("Please ensure all dependencies are installed:")
        print("  pip install -r requirements.txt")
        print()
        print("Note: agent-framework-azure-ai requires --pre flag:")
        print("  pip install agent-framework-azure-ai --pre")

    except Exception as e:
        print(f"❌ Error: {e}")
        logger.exception("Workflow failed")


if __name__ == "__main__":
    asyncio.run(main())
