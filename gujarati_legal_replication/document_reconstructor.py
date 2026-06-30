"""
Final Reconstruction Module

Rebuilds the final court-style judgement document from generated
structured sections. Handles:
- Court header formatting
- Legal layout reconstruction
- Numbering hierarchy rendering
- Proper spacing and indentation
- Output to DOCX and PDF formats
"""

import logging
from pathlib import Path
from typing import Optional

from .structured_parser import JudgementSchema, Section, SubSection

logger = logging.getLogger(__name__)


class DocumentReconstructor:
    """
    Reconstructs a court-format legal document from structured schema.
    Outputs formatted DOCX with proper legal layout.
    """
    
    def __init__(self, config=None):
        self.config = config
        # Default formatting parameters
        self.page_width_inches = 8.27  # A4
        self.page_height_inches = 11.69
        self.margin_top = 1.0
        self.margin_bottom = 1.0
        self.margin_left = 1.5
        self.margin_right = 1.0
        self.font_name = "Shruti"  # Gujarati font
        self.font_size_body = 12
        self.font_size_header = 14
        self.font_size_subheader = 12
        self.line_spacing = 1.5
    
    def reconstruct_to_text(self, schema: JudgementSchema) -> str:
        """
        Reconstruct judgement as formatted plain text.
        Useful for preview and validation.
        """
        lines = []
        
        # Header
        if schema.header:
            court_name = schema.header.get("court_name", "")
            lines.append(self._center_text(court_name))
            lines.append("")
            lines.append("=" * 60)
            lines.append("")
        
        # Case info
        if schema.case_info:
            ci = schema.case_info
            if ci.case_type:
                lines.append(self._center_text(f"{ci.case_type} No. {ci.case_number}/{ci.year}"))
            if ci.date_of_order:
                lines.append(f"Date: {ci.date_of_order}")
            if ci.coram:
                lines.append(f"Coram: {ci.coram}")
            lines.append("")
        
        # Parties
        if schema.parties:
            lines.append("-" * 40)
            for party in schema.parties:
                role_label = "અરજદાર" if party.role == "applicant" else "સામાવાળા"
                lines.append(f"{role_label}: {party.name}")
                if party.advocate:
                    lines.append(f"  Advocate: {party.advocate}")
            lines.append("-" * 40)
            lines.append("")
        
        # Sections
        for section in schema.sections:
            lines.extend(self._format_section_text(section))
            lines.append("")
        
        # Order
        if schema.order:
            lines.append("")
            lines.append(self._center_text("હુકમ / ORDER"))
            lines.append("")
            if "items" in schema.order:
                for item in schema.order["items"]:
                    lines.append(f"  {item.get('numbering', '')} {item.get('text', '')}")
            elif "raw_text" in schema.order:
                lines.append(schema.order["raw_text"])
            lines.append("")
        
        return "\n".join(lines)
    
    def _format_section_text(self, section: Section) -> list:
        """Format a section as text lines."""
        lines = []
        
        # Section title
        if section.title:
            lines.append(f"\n{'─' * 40}")
            lines.append(f"  {section.title}")
            lines.append(f"{'─' * 40}")
        
        # Main content
        if section.content:
            for para in section.content.split("\n"):
                if para.strip():
                    lines.append(f"    {para.strip()}")
        
        # Subsections with proper indentation
        for subsection in section.subsections:
            indent = "    " * (subsection.indent_level + 1)
            lines.append(f"{indent}{subsection.numbering} {subsection.content}")
        
        return lines
    
    def reconstruct_to_docx(self, schema: JudgementSchema, output_path: Path):
        """
        Reconstruct judgement as properly formatted DOCX.
        Preserves court document layout.
        """
        from docx import Document
        from docx.shared import Pt, Inches, Cm
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.section import WD_ORIENT
        
        doc = Document()
        
        # Page setup
        section = doc.sections[0]
        section.page_width = Inches(self.page_width_inches)
        section.page_height = Inches(self.page_height_inches)
        section.top_margin = Inches(self.margin_top)
        section.bottom_margin = Inches(self.margin_bottom)
        section.left_margin = Inches(self.margin_left)
        section.right_margin = Inches(self.margin_right)
        
        # Header
        if schema.header:
            court_name = schema.header.get("court_name", "")
            para = doc.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = para.add_run(court_name)
            run.bold = True
            run.font.size = Pt(self.font_size_header)
            run.font.name = self.font_name
            doc.add_paragraph()  # spacing
        
        # Case info
        if schema.case_info:
            ci = schema.case_info
            if ci.case_type:
                para = doc.add_paragraph()
                para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = para.add_run(f"{ci.case_type} No. {ci.case_number}/{ci.year}")
                run.bold = True
                run.font.size = Pt(self.font_size_body)
                run.font.name = self.font_name
            
            if ci.date_of_order:
                para = doc.add_paragraph()
                run = para.add_run(f"તારીખ / Date: {ci.date_of_order}")
                run.font.size = Pt(self.font_size_body)
                run.font.name = self.font_name
            
            if ci.coram:
                para = doc.add_paragraph()
                run = para.add_run(f"કોરમ / Coram: {ci.coram}")
                run.font.size = Pt(self.font_size_body)
                run.font.name = self.font_name
            
            doc.add_paragraph()
        
        # Parties
        if schema.parties:
            # Add horizontal rule
            para = doc.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = para.add_run("─" * 50)
            run.font.size = Pt(8)
            
            for party in schema.parties:
                role_label = "અરજદાર" if party.role == "applicant" else "સામાવાળા"
                para = doc.add_paragraph()
                run = para.add_run(f"{role_label}: ")
                run.bold = True
                run.font.size = Pt(self.font_size_body)
                run.font.name = self.font_name
                run = para.add_run(party.name)
                run.font.size = Pt(self.font_size_body)
                run.font.name = self.font_name
                
                if party.advocate:
                    para = doc.add_paragraph()
                    para.paragraph_format.left_indent = Inches(0.5)
                    run = para.add_run(f"એડવોકેટ: {party.advocate}")
                    run.font.size = Pt(self.font_size_body)
                    run.font.name = self.font_name
            
            # Closing rule
            para = doc.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = para.add_run("─" * 50)
            run.font.size = Pt(8)
            doc.add_paragraph()
        
        # Sections
        for sect in schema.sections:
            self._add_section_to_docx(doc, sect)
        
        # Order section
        if schema.order:
            para = doc.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = para.add_run("હુકમ / ORDER")
            run.bold = True
            run.font.size = Pt(self.font_size_subheader)
            run.font.name = self.font_name
            
            if "items" in schema.order:
                for item in schema.order["items"]:
                    para = doc.add_paragraph()
                    para.paragraph_format.left_indent = Inches(0.5)
                    text = f"{item.get('numbering', '')} {item.get('text', '')}"
                    run = para.add_run(text)
                    run.font.size = Pt(self.font_size_body)
                    run.font.name = self.font_name
            elif "raw_text" in schema.order:
                para = doc.add_paragraph()
                run = para.add_run(schema.order["raw_text"])
                run.font.size = Pt(self.font_size_body)
                run.font.name = self.font_name
        
        # Save
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(output_path))
        logger.info(f"Saved DOCX to: {output_path}")
    
    def _add_section_to_docx(self, doc, section: Section):
        """Add a formatted section to the DOCX document."""
        from docx.shared import Pt, Inches
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        
        # Section title
        if section.title:
            para = doc.add_paragraph()
            run = para.add_run(section.title)
            run.bold = True
            run.font.size = Pt(self.font_size_subheader)
            run.font.name = self.font_name
            run.underline = True
        
        # Main content paragraphs
        if section.content:
            for para_text in section.content.split("\n"):
                if para_text.strip():
                    para = doc.add_paragraph()
                    para.paragraph_format.first_line_indent = Inches(0.5)
                    run = para.add_run(para_text.strip())
                    run.font.size = Pt(self.font_size_body)
                    run.font.name = self.font_name
        
        # Subsections with indentation
        for subsection in section.subsections:
            para = doc.add_paragraph()
            indent_amount = 0.3 + (subsection.indent_level * 0.3)
            para.paragraph_format.left_indent = Inches(indent_amount)
            
            # Numbering in bold
            run = para.add_run(f"{subsection.numbering} ")
            run.bold = True
            run.font.size = Pt(self.font_size_body)
            run.font.name = self.font_name
            
            # Content
            run = para.add_run(subsection.content)
            run.font.size = Pt(self.font_size_body)
            run.font.name = self.font_name
        
        # Add spacing after section
        doc.add_paragraph()
    
    def _center_text(self, text: str, width: int = 60) -> str:
        """Center text within given width."""
        return text.center(width)
