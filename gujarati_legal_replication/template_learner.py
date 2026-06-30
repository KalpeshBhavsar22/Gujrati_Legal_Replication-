"""
Template Learning Module

Learns structural patterns from parsed judgements:
- Section ordering conventions
- Formatting patterns
- Drafting style norms
- Numbering structures
"""

import json
import logging
from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .structured_parser import JudgementSchema, Section

logger = logging.getLogger(__name__)


@dataclass
class SectionTemplate:
    """Template for a section type based on learned patterns."""
    section_type: str
    typical_titles: list = field(default_factory=list)
    avg_length: float = 0.0
    typical_position: float = 0.0  # normalized position [0, 1]
    numbering_style: str = ""  # "(1)", "1.", etc.
    typical_subsection_count: float = 0.0
    example_openings: list = field(default_factory=list)
    example_closings: list = field(default_factory=list)


@dataclass
class DocumentTemplate:
    """Learned template for a court document type."""
    document_type: str  # e.g., "Special Civil Application"
    section_order: list = field(default_factory=list)  # ordered section types
    section_templates: dict = field(default_factory=dict)  # type -> SectionTemplate
    header_format: dict = field(default_factory=dict)
    numbering_convention: str = ""
    total_examples: int = 0


class TemplateLearner:
    """
    Learns structural templates from a corpus of parsed judgements.
    Extracts:
    - Typical section ordering
    - Formatting conventions
    - Numbering styles
    - Drafting patterns
    """
    
    def __init__(self, config):
        self.config = config
        self.templates: dict = {}  # document_type -> DocumentTemplate
        self._section_orders = defaultdict(list)
        self._section_stats = defaultdict(lambda: defaultdict(list))
    
    def learn_from_schema(self, schema: JudgementSchema):
        """Learn patterns from a single parsed judgement."""
        doc_type = schema.case_info.case_type if schema.case_info else "general"
        
        # Track section order
        section_types = [s.section_type for s in schema.sections]
        self._section_orders[doc_type].append(section_types)
        
        # Track section statistics
        total_sections = len(schema.sections)
        for idx, section in enumerate(schema.sections):
            stats = self._section_stats[doc_type][section.section_type]
            stats.append({
                "title": section.title,
                "length": len(section.content),
                "position": idx / max(total_sections, 1),
                "subsection_count": len(section.subsections),
                "numbering": section.numbering,
                "opening": section.content[:100] if section.content else "",
                "closing": section.content[-100:] if section.content else "",
            })
    
    def learn_from_directory(self, parsed_dir: Path):
        """Learn templates from all parsed schemas in a directory."""
        parsed_dir = Path(parsed_dir)
        json_files = list(parsed_dir.glob("*.json"))
        
        logger.info(f"Learning templates from {len(json_files)} parsed judgements")
        
        for json_file in json_files:
            schema = JudgementSchema.load(json_file)
            self.learn_from_schema(schema)
        
        self._build_templates()
        logger.info(f"Built {len(self.templates)} document templates")
    
    def _build_templates(self):
        """Build final templates from accumulated statistics."""
        for doc_type, orders in self._section_orders.items():
            template = DocumentTemplate(
                document_type=doc_type,
                total_examples=len(orders)
            )
            
            # Find most common section order
            template.section_order = self._find_common_order(orders)
            
            # Build section templates
            for section_type, stats_list in self._section_stats[doc_type].items():
                section_template = self._build_section_template(section_type, stats_list)
                template.section_templates[section_type] = section_template
            
            # Determine numbering convention
            numbering_counts = Counter()
            for stats_list in self._section_stats[doc_type].values():
                for stat in stats_list:
                    if stat["numbering"]:
                        numbering_counts[stat["numbering"]] += 1
            
            if numbering_counts:
                template.numbering_convention = numbering_counts.most_common(1)[0][0]
            
            self.templates[doc_type] = template
    
    def _find_common_order(self, orders: list) -> list:
        """Find the most common section ordering pattern."""
        if not orders:
            return []
        
        # Use frequency-based ordering
        position_scores = defaultdict(list)
        for order in orders:
            for idx, section_type in enumerate(order):
                position_scores[section_type].append(idx)
        
        # Sort by average position
        avg_positions = {
            st: sum(positions) / len(positions)
            for st, positions in position_scores.items()
        }
        
        return sorted(avg_positions.keys(), key=lambda x: avg_positions[x])
    
    def _build_section_template(self, section_type: str, stats_list: list) -> SectionTemplate:
        """Build a template for a specific section type."""
        template = SectionTemplate(section_type=section_type)
        
        if not stats_list:
            return template
        
        # Typical titles
        title_counts = Counter(s["title"] for s in stats_list)
        template.typical_titles = [t for t, _ in title_counts.most_common(3)]
        
        # Average length
        template.avg_length = sum(s["length"] for s in stats_list) / len(stats_list)
        
        # Typical position
        template.typical_position = sum(s["position"] for s in stats_list) / len(stats_list)
        
        # Subsection count
        template.typical_subsection_count = (
            sum(s["subsection_count"] for s in stats_list) / len(stats_list)
        )
        
        # Example openings/closings
        template.example_openings = list(set(
            s["opening"] for s in stats_list if s["opening"]
        ))[:5]
        template.example_closings = list(set(
            s["closing"] for s in stats_list if s["closing"]
        ))[:5]
        
        # Numbering style
        numbering_styles = [s["numbering"] for s in stats_list if s["numbering"]]
        if numbering_styles:
            template.numbering_style = Counter(numbering_styles).most_common(1)[0][0]
        
        return template
    
    def get_template(self, document_type: str) -> Optional[DocumentTemplate]:
        """Get the learned template for a document type."""
        return self.templates.get(document_type) or self.templates.get("general")
    
    def save_templates(self, path: Path):
        """Save learned templates to disk."""
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        
        for doc_type, template in self.templates.items():
            filename = f"template_{doc_type.replace(' ', '_').lower()}.json"
            data = {
                "document_type": template.document_type,
                "section_order": template.section_order,
                "numbering_convention": template.numbering_convention,
                "total_examples": template.total_examples,
                "section_templates": {
                    st: {
                        "section_type": t.section_type,
                        "typical_titles": t.typical_titles,
                        "avg_length": t.avg_length,
                        "typical_position": t.typical_position,
                        "numbering_style": t.numbering_style,
                        "typical_subsection_count": t.typical_subsection_count,
                        "example_openings": t.example_openings,
                        "example_closings": t.example_closings,
                    }
                    for st, t in template.section_templates.items()
                }
            }
            filepath = path / filename
            filepath.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        
        logger.info(f"Saved {len(self.templates)} templates to {path}")
    
    def load_templates(self, path: Path):
        """Load previously learned templates from disk."""
        path = Path(path)
        
        for filepath in path.glob("template_*.json"):
            data = json.loads(filepath.read_text(encoding="utf-8"))
            
            template = DocumentTemplate(
                document_type=data["document_type"],
                section_order=data["section_order"],
                numbering_convention=data.get("numbering_convention", ""),
                total_examples=data.get("total_examples", 0),
            )
            
            for st, t_data in data.get("section_templates", {}).items():
                section_template = SectionTemplate(
                    section_type=t_data["section_type"],
                    typical_titles=t_data.get("typical_titles", []),
                    avg_length=t_data.get("avg_length", 0),
                    typical_position=t_data.get("typical_position", 0),
                    numbering_style=t_data.get("numbering_style", ""),
                    typical_subsection_count=t_data.get("typical_subsection_count", 0),
                    example_openings=t_data.get("example_openings", []),
                    example_closings=t_data.get("example_closings", []),
                )
                template.section_templates[st] = section_template
            
            self.templates[template.document_type] = template
        
        logger.info(f"Loaded {len(self.templates)} templates from {path}")
