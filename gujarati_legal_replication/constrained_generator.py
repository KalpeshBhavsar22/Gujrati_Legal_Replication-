"""
Structure-Constrained Generation Module

Generates legal judgement sections under strict structural constraints.
- Section-by-section generation (NOT full document at once)
- Template-guided output
- Format-aware generation with numbering preservation
"""

import json
import logging
from typing import Optional

from .structured_parser import Section, SubSection, JudgementSchema
from .template_learner import DocumentTemplate, SectionTemplate
from .section_retriever import RetrievalResult

logger = logging.getLogger(__name__)


class StructuredGenerator:
    """
    Generates legal judgement sections with structural constraints.
    
    Key principles:
    - Generate section-by-section, never full document at once
    - Use template schema to constrain output structure
    - Preserve numbering hierarchy
    - Maintain legal drafting style
    """
    
    def __init__(self, config):
        self.config = config
        self._client = None
    
    def _init_client(self):
        """Initialize the LLM client (Gemini via OpenAI-compatible API)."""
        if self._client is None:
            import os
            from openai import OpenAI
            
            api_key = self.config.api_key or os.environ.get("GEMINI_API_KEY")
            self._client = OpenAI(
                base_url=self.config.api_base or "https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=api_key,
            )
    
    def generate_section(
        self,
        section_type: str,
        template: Optional[SectionTemplate],
        retrieved_examples: list,
        case_context: dict,
        previous_sections: list = None,
    ) -> Section:
        """
        Generate a single section using template constraints.
        
        Args:
            section_type: Type of section to generate (e.g., "facts", "order")
            template: Learned template for this section type
            retrieved_examples: Similar sections from retrieval
            case_context: Current case information
            previous_sections: Previously generated sections for context
            
        Returns:
            Generated Section object
        """
        self._init_client()
        
        prompt = self._build_section_prompt(
            section_type, template, retrieved_examples, case_context, previous_sections
        )
        
        response = self._client.chat.completions.create(
            model=self.config.model_name,
            messages=[
                {"role": "system", "content": self._get_system_prompt()},
                {"role": "user", "content": prompt},
            ],
            max_tokens=self.config.max_tokens_per_section,
            temperature=self.config.temperature,
            top_p=self.config.top_p,
        )
        
        generated_text = response.choices[0].message.content
        
        # Parse generated text into structured section
        section = self._parse_generated_section(generated_text, section_type, template)
        
        return section
    
    def generate_full_judgement(
        self,
        document_template: DocumentTemplate,
        case_context: dict,
        retriever=None,
    ) -> JudgementSchema:
        """
        Generate complete judgement following template structure.
        If only generic sections available, generates full judgement in one pass.
        """
        self._init_client()
        schema = JudgementSchema()
        schema.metadata = {"generated": True, "template_type": document_template.document_type}
        
        # Retrieve reference examples for style
        retrieved = []
        if retriever:
            retrieved = retriever.retrieve_for_template(
                section_type="general",
                context=json.dumps(case_context, ensure_ascii=False)[:200],
                top_k=3,
            )
        
        # Build a comprehensive prompt for full judgement generation
        prompt = self._build_full_judgement_prompt(case_context, retrieved)
        
        logger.info("Generating full judgement...")
        response = self._client.chat.completions.create(
            model=self.config.model_name,
            messages=[
                {"role": "system", "content": self._get_system_prompt()},
                {"role": "user", "content": prompt},
            ],
            max_tokens=self.config.max_tokens_per_section,
            temperature=self.config.temperature,
            top_p=self.config.top_p,
        )
        
        generated_text = response.choices[0].message.content
        
        # Parse into sections
        sections = self._parse_full_judgement(generated_text)
        schema.sections = sections
        return schema
    
    def _build_full_judgement_prompt(self, case_context: dict, retrieved_examples: list) -> str:
        """Build prompt for generating a document by replicating reference format."""
        parts = []
        
        parts.append("## TASK: REPLICATE the format of the REFERENCE DOCUMENT below, substituting new case details.")
        parts.append("")
        parts.append("You must produce a document that is STRUCTURALLY IDENTICAL to the reference —")
        parts.append("same sections, same order, same formatting, same closing formula.")
        parts.append("Only change the case-specific details (names, dates, locations, facts, outcome).")
        parts.append("")
        
        # Reference document (full text from parsed judgements)
        if retrieved_examples:
            parts.append("## REFERENCE DOCUMENT (REPLICATE THIS FORMAT EXACTLY):")
            parts.append("")
            # Use the longest/best reference
            best = max(retrieved_examples, key=lambda r: len(r.section.content))
            parts.append(best.section.content[:6000])
            parts.append("")
        elif case_context.get("reference_text"):
            parts.append("## REFERENCE DOCUMENT (REPLICATE THIS FORMAT EXACTLY):")
            parts.append("")
            parts.append(case_context["reference_text"][:6000])
            parts.append("")
        
        # New case context
        parts.append("## NEW CASE DETAILS (substitute these into the format above):")
        # Remove reference_text from context to avoid duplication in prompt
        ctx_for_prompt = {k: v for k, v in case_context.items() if k != "reference_text"}
        parts.append(json.dumps(ctx_for_prompt, ensure_ascii=False, indent=2))
        parts.append("")
        
        parts.append("## INSTRUCTIONS:")
        parts.append("- REPLICATE the reference document's EXACT structure and format")
        parts.append("- Same header style, same section ordering, same numbering pattern")
        parts.append("- Same closing formula and signature block format")
        parts.append("- Same distribution list format (પ્રતિ, નકલ રવાના)")
        parts.append("- Substitute ONLY the new case details into the same structure")
        parts.append("- Match paragraph density and length of the reference")
        parts.append("- Do NOT add sections that don't exist in the reference")
        parts.append("- Do NOT add your own legal analysis or citations unless the reference has them")
        parts.append("- Output the complete document directly")
        
        return "\n".join(parts)
    
    def _parse_full_judgement(self, generated_text: str) -> list:
        """Parse a full generated judgement into sections."""
        import re
        
        # Try to split by common Gujarati section headers
        section_markers = [
            (r"હકીકત|FACTS", "facts"),
            (r"દલીલ|ARGUMENTS", "arguments"),
            (r"અવલોકન|OBSERVATIONS", "observations"),
            (r"તારણ|FINDINGS|હુકમ|ORDER|આદેશ", "order"),
        ]
        
        lines = generated_text.strip().split("\n")
        sections = []
        current_lines = []
        current_type = "header"
        
        for line in lines:
            matched = False
            for pattern, stype in section_markers:
                if re.search(pattern, line, re.IGNORECASE) and len(line.strip()) < 80:
                    # Save previous section
                    if current_lines:
                        content = "\n".join(current_lines).strip()
                        if content:
                            sections.append(Section(
                                id=str(len(sections) + 1),
                                section_type=current_type,
                                title=current_type,
                                content=content,
                                subsections=[],
                            ))
                    current_lines = [line]
                    current_type = stype
                    matched = True
                    break
            if not matched:
                current_lines.append(line)
        
        # Add last section
        if current_lines:
            content = "\n".join(current_lines).strip()
            if content:
                sections.append(Section(
                    id=str(len(sections) + 1),
                    section_type=current_type,
                    title=current_type,
                    content=content,
                    subsections=[],
                ))
        
        # If no sections detected, put everything in one
        if not sections:
            sections.append(Section(
                id="1",
                section_type="general",
                title="general",
                content=generated_text.strip(),
                subsections=[],
            ))
        
        return sections
    
    def _get_system_prompt(self) -> str:
        """System prompt for legal judgement generation."""
        return """તમે ગુજરાત મહેસૂલ વિભાગના કાનૂની હુકમ/ચુકાદા ફોર્મેટ રિપ્લિકેટર છો.
You are a FORMAT REPLICATOR for Gujarat Revenue Department legal orders.

Your task is to REPLICATE the exact format, structure, style, numbering, and layout of the provided REFERENCE DOCUMENT — substituting only the case-specific details (names, dates, survey numbers, locations, facts) from the NEW CASE CONTEXT.

RULES:
- REPLICATE the reference document's structure EXACTLY — same sections, same order, same formatting
- Do NOT invent new sections that don't exist in the reference
- Do NOT add your own legal analysis, arguments, or observations unless the reference has them
- MATCH the reference's numbering style: (૧), (૧.૧), (૧.૨), (૨), etc.
- MATCH the reference's header format, closing format, signature block, and distribution list
- Use the SAME legal terminology and phrasing patterns from the reference
- Substitute ONLY the case-specific details from the new case context
- Preserve the reference's paragraph lengths and density
- Output the complete document text directly, no meta-commentary
- If the reference has a specific closing formula (e.g. 'ગુજરાતના રાજ્યપાલશ્રીના હુકમથી...'), use that EXACT formula"""
    
    def _build_section_prompt(
        self,
        section_type: str,
        template: Optional[SectionTemplate],
        retrieved_examples: list,
        case_context: dict,
        previous_sections: list = None,
    ) -> str:
        """Build the generation prompt for a section."""
        parts = []
        
        # Section type and structure requirements
        parts.append(f"## SECTION TO GENERATE: {section_type.upper()}")
        parts.append("")
        
        # Template constraints
        if template:
            parts.append("## STRUCTURAL TEMPLATE:")
            if template.typical_titles:
                parts.append(f"- Typical title: {template.typical_titles[0]}")
            parts.append(f"- Expected length: ~{int(template.avg_length)} characters")
            parts.append(f"- Expected subsections: ~{int(template.typical_subsection_count)}")
            if template.numbering_style:
                parts.append(f"- Numbering style: {template.numbering_style}")
            parts.append("")
        
        # Reference examples from retrieval
        if retrieved_examples:
            parts.append("## REFERENCE EXAMPLES (follow this style and format):")
            for i, result in enumerate(retrieved_examples[:3], 1):
                parts.append(f"\n### Example {i} (from: {result.source_file}):")
                parts.append(f"Title: {result.section.title}")
                # Limit content to avoid token overflow
                content = result.section.content[:800]
                parts.append(f"Content:\n{content}")
                if result.section.subsections:
                    parts.append("Subsections:")
                    for ss in result.section.subsections[:5]:
                        parts.append(f"  {ss.numbering} {ss.content[:200]}")
            parts.append("")
        
        # Case context
        parts.append("## CURRENT CASE CONTEXT:")
        parts.append(json.dumps(case_context, ensure_ascii=False, indent=2)[:1000])
        parts.append("")
        
        # Previous sections for continuity
        if previous_sections:
            parts.append("## PREVIOUSLY GENERATED SECTIONS (for continuity):")
            for section in previous_sections[-2:]:  # Last 2 sections only
                parts.append(f"- {section.title}: {section.content[:200]}...")
            parts.append("")
        
        # Generation instruction
        parts.append("## INSTRUCTION:")
        parts.append(f"Generate the '{section_type}' section following the exact structure, "
                     f"numbering, and formatting shown in the reference examples. "
                     f"Use formal Gujarati legal language. "
                     f"Output the section content directly without any preamble.")
        
        return "\n".join(parts)
    
    def _parse_generated_section(
        self,
        generated_text: str,
        section_type: str,
        template: Optional[SectionTemplate],
    ) -> Section:
        """Parse generated text back into a structured Section."""
        import re
        
        lines = generated_text.strip().split("\n")
        
        # Extract title (first line if it looks like a title)
        title = ""
        content_start = 0
        if lines and not re.match(r"^\(\d+\)", lines[0]):
            title = lines[0].strip(": \t")
            content_start = 1
        
        if not title and template and template.typical_titles:
            title = template.typical_titles[0]
        
        # Parse subsections (numbered items)
        subsections = []
        main_content_parts = []
        
        numbering_pattern = re.compile(r"^\((\d+(?:\.\d+)?)\)\s*(.+)")
        
        for line in lines[content_start:]:
            match = numbering_pattern.match(line.strip())
            if match:
                sub_id = match.group(1)
                sub_content = match.group(2)
                subsection = SubSection(
                    id=sub_id,
                    numbering=f"({sub_id})",
                    content=sub_content.strip(),
                    indent_level=1 if "." in sub_id else 0
                )
                subsections.append(subsection)
            else:
                main_content_parts.append(line)
        
        content = "\n".join(main_content_parts).strip()
        
        return Section(
            id="0",  # Will be assigned by orchestrator
            section_type=section_type,
            title=title or section_type,
            content=content,
            subsections=subsections,
        )
