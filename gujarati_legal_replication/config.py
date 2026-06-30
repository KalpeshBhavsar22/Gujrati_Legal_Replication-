"""
Configuration for the Gujarati Legal Judgement Replication System.
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OCRConfig:
    """OCR layer configuration."""
    language: str = "gu"  # Gujarati
    use_gpu: bool = True

    # Google Gemini API (free tier: 15 RPM, 1500 RPD)
    # Get key at: https://aistudio.google.com/apikey
    # Set env var: GEMINI_API_KEY=your_key
    glm_api_base: Optional[str] = "https://generativelanguage.googleapis.com/v1beta/openai/"
    glm_api_key: Optional[str] = None  # reads from GEMINI_API_KEY env var
    glm_model_name: str = "gemini-2.5-flash"


@dataclass
class LayoutConfig:
    """Layout understanding configuration."""
    engine: str = "pdfplumber"  # "pdfplumber", "pymupdf", "docling"
    detect_headers: bool = True
    detect_tables: bool = True
    detect_numbering: bool = True
    min_section_gap: float = 15.0  # minimum vertical gap to detect section break
    header_font_size_threshold: float = 12.0

    # Layout capture output toggles
    save_visual_overlay: bool = True   # Option 1: PNG bounding box overlay per page
    save_layout_json: bool = True      # Option 3: JSON spatial map export
    save_table_json: bool = True       # Option 2: pdfplumber table extraction


@dataclass
class ParserConfig:
    """Structured parser configuration."""
    numbering_patterns: list = field(default_factory=lambda: [
        r"^\((\d+)\)",           # (1), (2)
        r"^\((\d+\.\d+)\)",     # (1.1), (1.2)
        r"^(\d+)\.",            # 1., 2.
        r"^(\d+\.\d+)\.",      # 1.1., 1.2.
        r"^[અ-ૐ]\)",           # Gujarati numbered lists
    ])
    section_keywords: list = field(default_factory=lambda: [
        "હુકમ", "આદેશ", "હકીકત", "દલીલ", "અવલોકન",
        "તારણ", "સંદર્ભ", "અરજદાર", "સામાવાળા",
        "ORDER", "FACTS", "ARGUMENTS", "OBSERVATIONS",
        "FINDINGS", "REFERENCES"
    ])


@dataclass
class RetrievalConfig:
    """Section-wise retrieval configuration."""
    vector_db: str = "faiss"  # "faiss" or "chromadb"
    embedding_model: str = "gemini-embedding-001"  # Google Gemini embedding (free)
    embedding_api_base: str = "https://generativelanguage.googleapis.com/v1beta/"
    index_path: str = "data/vector_index"
    top_k: int = 5
    retrieval_mode: str = "section"  # "section" (not "semantic_chunk")


@dataclass
class GenerationConfig:
    """Constrained generation configuration."""
    model_name: str = "gemini-2.5-flash"
    max_tokens_per_section: int = 8192
    temperature: float = 0.1
    top_p: float = 0.85
    api_base: Optional[str] = "https://generativelanguage.googleapis.com/v1beta/openai/"
    api_key: Optional[str] = None  # reads from GEMINI_API_KEY env var


@dataclass
class PipelineConfig:
    """Main pipeline configuration."""
    input_dir: Path = Path("data/input_pdfs")
    output_dir: Path = Path("data/output")
    template_dir: Path = Path("data/templates")
    parsed_dir: Path = Path("data/parsed")

    # Layout capture output directories
    layout_overlay_dir: Path = Path("data/layout_overlays")   # Option 1: PNG overlays
    layout_json_dir: Path = Path("data/layout_json")          # Option 3: JSON spatial maps
    table_json_dir: Path = Path("data/tables")                # Option 2: extracted tables

    ocr: OCRConfig = field(default_factory=OCRConfig)
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    parser: ParserConfig = field(default_factory=ParserConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    generation: GenerationConfig = field(default_factory=GenerationConfig)

    def ensure_dirs(self):
        """Create all required directories."""
        for d in [
            self.input_dir,
            self.output_dir,
            self.template_dir,
            self.parsed_dir,
            self.layout_overlay_dir,
            self.layout_json_dir,
            self.table_json_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)