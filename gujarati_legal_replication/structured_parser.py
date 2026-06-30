"""
Structured Parser Module

Converts layout analysis into structured JSON schema
representing the legal judgement's complete structure.
"""

import json
import re
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

from .layout_analyzer import LayoutAnalysis, LayoutSection, LayoutBlock

logger = logging.getLogger(__name__)


@dataclass
class PartyInfo:
    """Structured party information."""
    role: str  # "applicant", "respondent"
    name: str
    address: Optional[str] = None
    advocate: Optional[str] = None
    designation: Optional[str] = None


@dataclass
class CaseInfo:
    """Structured case metadata."""
    court_name: str = ""
    case_type: str = ""  # "Special Civil Application", "Writ Petition", etc.
    case_number: str = ""
    year: str = ""
    date_of_order: str = ""
    coram: str = ""  # Judge(s)
    bench: str = ""


@dataclass
class SubSection:
    """A sub-section within a main section."""
    id: str  # e.g., "1.1", "1.2"
    numbering: str  # e.g., "(1.1)"
    content: str
    indent_level: int = 0


@dataclass
class Section:
    """A main section of the judgement."""
    id: str  # sequential id
    section_type: str  # "facts", "arguments", "observations", "findings", "order"
    title: str
    content: str
    subsections: list = field(default_factory=list)  # List[SubSection]
    numbering: Optional[str] = None
    page_start: int = 0
    page_end: int = 0


@dataclass
class JudgementSchema:
    """Complete structured schema of a legal judgement."""
    header: dict = field(default_factory=dict)
    case_info: Optional[CaseInfo] = None
    parties: list = field(default_factory=list)  # List[PartyInfo]
    sections: list = field(default_factory=list)  # List[Section]
    order: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "header": self.header,
            "case_info": asdict(self.case_info) if self.case_info else {},
            "parties": [asdict(p) for p in self.parties],
            "sections": [
                {
                    "id": s.id,
                    "section_type": s.section_type,
                    "title": s.title,
                    "content": s.content,
                    "subsections": [asdict(ss) for ss in s.subsections],
                    "numbering": s.numbering,
                    "page_start": s.page_start,
                    "page_end": s.page_end,
                }
                for s in self.sections
            ],
            "order": self.order,
            "metadata": self.metadata,
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
    
    def save(self, path: Path):
        """Save structured schema to JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        logger.info(f"Saved structured schema to: {path}")
    
    @classmethod
    def load(cls, path: Path) -> "JudgementSchema":
        """Load structured schema from JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        schema = cls()
        schema.header = data.get("header", {})
        
        ci = data.get("case_info", {})
        if ci:
            schema.case_info = CaseInfo(**ci)
        
        schema.parties = [PartyInfo(**p) for p in data.get("parties", [])]
        
        for s in data.get("sections", []):
            subsections = [SubSection(**ss) for ss in s.get("subsections", [])]
            section = Section(
                id=s["id"],
                section_type=s["section_type"],
                title=s["title"],
                content=s["content"],
                subsections=subsections,
                numbering=s.get("numbering"),
                page_start=s.get("page_start", 0),
                page_end=s.get("page_end", 0),
            )
            schema.sections.append(section)
        
        schema.order = data.get("order", {})
        schema.metadata = data.get("metadata", {})
        return schema


class StructuredParser:
    """
    Converts LayoutAnalysis into a JudgementSchema.
    Parses headers, case info, parties, numbered sections, and orders.
    """
    
    def __init__(self, config):
        self.config = config
        
        # Party role patterns
        self.applicant_patterns = [
            r"અરજદાર", r"APPLICANT", r"PETITIONER", r"याचिकाकर्ता",
        ]
        self.respondent_patterns = [
            r"સામાવાળા", r"RESPONDENT", r"OPPONENT", r"प्रतिवादी",
        ]
        
        # Advocate patterns
        self.advocate_patterns = [
            r"(?:એડવોકેટ|ADVOCATE|ADV\.?|MR\.|MS\.|MRS\.)\s+(.+)",
            r"(?:વકીલ|COUNSEL)\s*[:\-]?\s*(.+)",
        ]
    
    def parse(self, layout: LayoutAnalysis, source_file: str = "") -> JudgementSchema:
        """Convert layout analysis to structured judgement schema."""
        schema = JudgementSchema()
        schema.metadata = {
            "source_file": source_file,
            "total_pages": layout.page_count,
            "section_count": len(layout.sections),
        }
        
        section_counter = 0
        
        for layout_section in layout.sections:
            if layout_section.section_type == "court_header":
                schema.header = self._parse_header(layout_section)
            
            elif layout_section.section_type == "case_info":
                schema.case_info = self._parse_case_info(layout_section)
            
            elif layout_section.section_type == "party_info":
                parties = self._parse_parties(layout_section)
                schema.parties.extend(parties)
            
            elif layout_section.section_type == "order":
                schema.order = self._parse_order(layout_section)
            
            else:  # body_section
                section_counter += 1
                section = self._parse_body_section(layout_section, section_counter)
                schema.sections.append(section)
        
        return schema
    
    def _parse_header(self, layout_section: LayoutSection) -> dict:
        """Parse court header information."""
        text = " ".join(b.text for b in layout_section.blocks)
        return {
            "court_name": text.strip(),
            "raw_text": text,
        }
    
    def _parse_case_info(self, layout_section: LayoutSection) -> CaseInfo:
        """Parse case metadata."""
        text = " ".join(b.text for b in layout_section.blocks)
        
        case_info = CaseInfo()
        
        # Extract case number
        num_match = re.search(r"(?:NO\.?|નંબર)\s*(\d+)", text, re.IGNORECASE)
        if num_match:
            case_info.case_number = num_match.group(1)
        
        # Extract year
        year_match = re.search(r"\b(20\d{2}|19\d{2})\b", text)
        if year_match:
            case_info.year = year_match.group(1)
        
        # Extract case type
        type_patterns = [
            (r"સ્પેશિયલ\s*સિવિલ\s*અરજી", "Special Civil Application"),
            (r"SPECIAL\s*CIVIL\s*APPLICATION", "Special Civil Application"),
            (r"રિટ\s*પિટિશન", "Writ Petition"),
            (r"WRIT\s*PETITION", "Writ Petition"),
            (r"ફર્સ્ટ\s*અપીલ", "First Appeal"),
            (r"FIRST\s*APPEAL", "First Appeal"),
        ]
        for pattern, case_type in type_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                case_info.case_type = case_type
                break
        
        # Extract date
        date_match = re.search(r"(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})", text)
        if date_match:
            case_info.date_of_order = date_match.group(1)
        
        return case_info
    
    def _parse_parties(self, layout_section: LayoutSection) -> list:
        """Parse party information (applicant/respondent)."""
        parties = []
        
        for block in layout_section.blocks:
            text = block.text
            role = None
            
            for pattern in self.applicant_patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    role = "applicant"
                    break
            
            if not role:
                for pattern in self.respondent_patterns:
                    if re.search(pattern, text, re.IGNORECASE):
                        role = "respondent"
                        break
            
            if role:
                # Extract name (text after role keyword)
                name = re.sub(
                    "|".join(self.applicant_patterns + self.respondent_patterns),
                    "", text, flags=re.IGNORECASE
                ).strip(" :-\t")
                
                party = PartyInfo(role=role, name=name)
                
                # Try to find advocate
                for adv_pattern in self.advocate_patterns:
                    adv_match = re.search(adv_pattern, text, re.IGNORECASE)
                    if adv_match:
                        party.advocate = adv_match.group(1).strip()
                        break
                
                parties.append(party)
        
        return parties
    
    def _parse_body_section(self, layout_section: LayoutSection, counter: int) -> Section:
        """Parse a body section with potential subsections."""
        title = layout_section.title or f"Section {counter}"
        section_type = self._infer_section_type_from_title(title)
        
        # Separate numbered items as subsections
        subsections = []
        main_content_parts = []
        
        for block in layout_section.blocks:
            if block.block_type == "numbered_item" and block.numbering:
                # This is a sub-item
                sub_id = f"{counter}.{len(subsections) + 1}"
                subsection = SubSection(
                    id=sub_id,
                    numbering=block.numbering,
                    content=block.text,
                    indent_level=block.indent_level
                )
                subsections.append(subsection)
            else:
                main_content_parts.append(block.text)
        
        content = "\n".join(main_content_parts)
        
        return Section(
            id=str(counter),
            section_type=section_type,
            title=title,
            content=content,
            subsections=subsections,
            page_start=layout_section.page_start,
            page_end=layout_section.page_end,
        )
    
    def _parse_order(self, layout_section: LayoutSection) -> dict:
        """Parse the order/disposition section."""
        text = "\n".join(b.text for b in layout_section.blocks)
        
        # Extract numbered order items
        items = []
        for block in layout_section.blocks:
            if block.numbering:
                items.append({
                    "numbering": block.numbering,
                    "text": block.text
                })
        
        return {
            "raw_text": text,
            "items": items,
        }
    
    def _infer_section_type_from_title(self, title: str) -> str:
        """Map section title to standardized type."""
        title_lower = title.lower()
        
        type_map = {
            "facts": ["હકીકત", "facts", "fact"],
            "arguments": ["દલીલ", "arguments", "argument", "submissions"],
            "observations": ["અવલોકન", "observations", "observation"],
            "findings": ["તારણ", "findings", "finding", "conclusion"],
            "order": ["હુકમ", "આદેશ", "order", "disposition"],
            "references": ["સંદર્ભ", "references", "reference"],
        }
        
        for section_type, keywords in type_map.items():
            if any(kw in title_lower for kw in keywords):
                return section_type
        
        return "general"
