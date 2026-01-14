"""
PDF Generator Utilities for Best Practices Reports.
Generates professionally formatted PDF reports from best practices data.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from fpdf import FPDF
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

from .legacy_utils import setup_logger

logger = setup_logger(__name__)


def print_best_practices_report(result: dict) -> None:
    """Print comprehensive best practices report to console."""
    print("\n" + "=" * 80)
    print("🎯 AZURE BEST PRACTICES REPORT")
    print("=" * 80)
    
    # Data sources
    data_sources = result.get('data_sources', [result.get('data_source', 'unknown')])
    print(f"\n📊 Data Sources: {', '.join(data_sources) if isinstance(data_sources, list) else data_sources}")
    print(f"📈 Total Recommendations: {result.get('total_recommendations', 'N/A')}")
    
    # Service Recommendations
    print("\n" + "-" * 80)
    print("📋 SERVICE RECOMMENDATIONS")
    print("-" * 80)
    
    service_recs = result.get('service_recommendations', [])
    for idx, service in enumerate(service_recs, 1):
        service_name = service.get('service_name', 'Unknown Service')
        best_practices = service.get('best_practices', [])
        sources = service.get('sources', [service.get('source', 'unknown')])
        
        print(f"\n🔷 {idx}. {service_name}")
        print(f"   Sources: {', '.join(sources) if isinstance(sources, list) else sources}")
        print(f"   Best Practices ({len(best_practices)} found):")
        
        for bp_idx, bp in enumerate(best_practices, 1):
            # Determine source from prefix
            if "[From index]" in bp or "[From search" in bp:
                icon = "🔍"
            elif "[From MS Learn]" in bp or "[From microsoft" in bp.lower():
                icon = "📚"
            else:
                icon = "✅"
            print(f"      {bp_idx}. {icon} {bp}")
    
    # Architecture Checklist
    print("\n" + "-" * 80)
    print("✅ ARCHITECTURE CHECKLIST")
    print("-" * 80)
    
    checklist = result.get('architecture_checklist', [])
    for idx, item in enumerate(checklist, 1):
        print(f"   [ ] {idx}. {item}")
    
    # Summary
    print("\n" + "-" * 80)
    print("📝 SUMMARY")
    print("-" * 80)
    print(f"   {result.get('summary', 'No summary available')}")
    
    print("\n" + "=" * 80)
    print("✅ BEST PRACTICES REPORT COMPLETE")
    print("=" * 80 + "\n")


def save_best_practices_pdf(result: dict, output_path: Optional[str] = None) -> str:
    """
    Save the best practices report as a professionally formatted PDF.
    
    Args:
        result: The best practices result dictionary
        output_path: Optional path for the PDF. If None, saves to outputs folder.
    
    Returns:
        Path to the saved PDF file
    """
    if not PDF_AVAILABLE:
        raise ImportError("fpdf2 is required for PDF generation. Install with: pip install fpdf2")
    
    # Create output directory
    if output_path is None:
        output_dir = Path(__file__).parent.parent.parent / 'outputs' / 'best_practices'
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = str(output_dir / f"best_practices_report_{timestamp}.pdf")
    
    # Create PDF with custom class for better formatting
    class BestPracticesPDF(FPDF):
        def header(self):
            self.set_font('Helvetica', 'B', 12)
            self.set_text_color(0, 102, 204)  # Azure blue
            self.cell(0, 10, 'Azure Best Practices Report', align='C', new_x='LMARGIN', new_y='NEXT')
            self.set_draw_color(0, 102, 204)
            self.line(10, 20, 200, 20)
            self.ln(5)
        
        def footer(self):
            self.set_y(-15)
            self.set_font('Helvetica', 'I', 8)
            self.set_text_color(128, 128, 128)
            self.cell(0, 10, f'Page {self.page_no()}/{{nb}} | Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}', align='C')
        
        def chapter_title(self, title: str, icon: str = ""):
            self.set_font('Helvetica', 'B', 14)
            self.set_text_color(0, 51, 102)
            self.set_fill_color(240, 248, 255)  # Light blue background
            display_title = f"{icon} {title}" if icon else title
            self.cell(0, 10, display_title, fill=True, new_x='LMARGIN', new_y='NEXT')
            self.ln(3)
        
        def section_title(self, title: str, number: int = 0):
            self.set_font('Helvetica', 'B', 11)
            self.set_text_color(0, 102, 153)
            prefix = f"{number}. " if number > 0 else ""
            self.cell(0, 8, f"{prefix}{title}", new_x='LMARGIN', new_y='NEXT')
            self.ln(1)
        
        def body_text(self, text: str, indent: int = 0):
            self.set_font('Helvetica', '', 10)
            self.set_text_color(51, 51, 51)
            # Handle long text with word wrap
            self.set_x(10 + indent)
            # Clean and encode text properly
            clean_text = text.encode('latin-1', 'replace').decode('latin-1')
            self.multi_cell(0, 5, clean_text)
        
        def bullet_point(self, text: str, bullet: str = "*", indent: int = 10):
            self.set_font('Helvetica', '', 10)
            self.set_text_color(51, 51, 51)
            self.set_x(10 + indent)
            # Clean text for PDF encoding
            clean_text = text.encode('latin-1', 'replace').decode('latin-1')
            self.multi_cell(0, 5, f"  {bullet} {clean_text}")
        
        def checklist_item(self, text: str, number: int):
            self.set_font('Helvetica', '', 10)
            self.set_text_color(51, 51, 51)
            clean_text = text.encode('latin-1', 'replace').decode('latin-1')
            self.cell(0, 6, f"    [ ] {number}. {clean_text}", new_x='LMARGIN', new_y='NEXT')
        
        def info_box(self, label: str, value: str):
            self.set_font('Helvetica', 'B', 10)
            self.set_text_color(0, 102, 153)
            self.cell(50, 6, f"{label}:")
            self.set_font('Helvetica', '', 10)
            self.set_text_color(51, 51, 51)
            clean_value = str(value).encode('latin-1', 'replace').decode('latin-1')
            self.cell(0, 6, clean_value, new_x='LMARGIN', new_y='NEXT')
    
    # Create PDF document
    pdf = BestPracticesPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)
    
    # Title Section
    pdf.set_font('Helvetica', 'B', 20)
    pdf.set_text_color(0, 51, 102)
    pdf.cell(0, 15, 'Azure Architecture Best Practices', align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(5)
    
    # Report Metadata
    pdf.set_draw_color(200, 200, 200)
    pdf.set_fill_color(250, 250, 250)
    pdf.rect(10, pdf.get_y(), 190, 25, style='F')
    pdf.ln(3)
    
    data_sources = result.get('data_sources', [result.get('data_source', 'Azure AI Search')])
    sources_str = ', '.join(data_sources) if isinstance(data_sources, list) else str(data_sources)
    pdf.info_box("Data Sources", sources_str)
    pdf.info_box("Total Recommendations", str(result.get('total_recommendations', 'N/A')))
    pdf.info_box("Generated", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    pdf.ln(10)
    
    # Service Recommendations
    pdf.chapter_title("Service Recommendations", "")
    
    service_recs = result.get('service_recommendations', [])
    for idx, service in enumerate(service_recs, 1):
        service_name = service.get('service_name', 'Unknown Service')
        best_practices = service.get('best_practices', [])
        sources = service.get('sources', [service.get('source', 'unknown')])
        
        pdf.section_title(service_name, idx)
        
        # Sources info
        pdf.set_font('Helvetica', 'I', 9)
        pdf.set_text_color(100, 100, 100)
        sources_text = ', '.join(sources) if isinstance(sources, list) else str(sources)
        pdf.cell(0, 5, f"Sources: {sources_text} | {len(best_practices)} recommendations", new_x='LMARGIN', new_y='NEXT')
        pdf.ln(2)
        
        # Best practices
        for bp_idx, bp in enumerate(best_practices, 1):
            # Determine bullet based on source
            if "[From index]" in bp or "[From search" in bp:
                bullet = "[Search]"
            elif "[From MS Learn]" in bp or "[From microsoft" in bp.lower():
                bullet = "[Learn]"
            else:
                bullet = f"{bp_idx}."
            
            # Clean the text of source prefixes for cleaner display
            clean_bp = re.sub(r'\[From (index|search|MS Learn|microsoft learn)\]\s*', '', bp, flags=re.IGNORECASE)
            pdf.bullet_point(clean_bp, bullet, indent=5)
        
        pdf.ln(3)
    
    # Architecture Checklist
    pdf.add_page()
    pdf.chapter_title("Architecture Checklist", "")
    
    checklist = result.get('architecture_checklist', [])
    for idx, item in enumerate(checklist, 1):
        pdf.checklist_item(item, idx)
    pdf.ln(5)
    
    # Summary Section
    pdf.chapter_title("Summary", "")
    summary = result.get('summary', 'No summary available')
    pdf.body_text(summary)
    pdf.ln(10)
    
    # Footer note
    pdf.set_font('Helvetica', 'I', 9)
    pdf.set_text_color(128, 128, 128)
    pdf.multi_cell(0, 5, 
        "This report was generated using Azure AI Search knowledge base and Microsoft Learn documentation. "
        "Best practices should be validated against current Azure documentation for the latest recommendations."
    )
    
    # Save PDF
    pdf.output(output_path)
    logger.info(f"Best practices PDF saved to: {output_path}")
    
    return output_path
