"""
OCR Extraction Module

Handles PDF → text extraction with coordinate preservation.
Engine: Google Gemini 2.0 Flash (free API, ~3-8 sec/page).
For digital PDFs with embedded text, uses PyMuPDF native extraction.
"""

import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class OCRWord:
    """Single word/token from OCR with position."""
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float
    page_num: int


@dataclass
class OCRLine:
    """A line of text with bounding box."""
    text: str
    words: list  # List[OCRWord]
    x0: float
    y0: float
    x1: float
    y1: float
    page_num: int


@dataclass
class OCRPage:
    """All OCR results for a single page."""
    page_num: int
    width: float
    height: float
    lines: list  # List[OCRLine]


@dataclass
class OCRDocument:
    """Complete OCR output for a document."""
    file_path: str
    pages: list  # List[OCRPage]
    total_pages: int


class GLMOCRExtractor:
    """
    Vision OCR extraction using Google Gemini 2.0 Flash (free API).
    
    Setup:
        1. Get free API key at: https://aistudio.google.com/apikey
        2. Set environment variable: GEMINI_API_KEY=your_key
    
    Free tier limits: 15 RPM, 1500 requests/day, 1M tokens/min
    Speed: ~3-8 sec per page
    Cost: Free
    """
    
    def __init__(self, config):
        self.config = config
        self._client = None
    
    def _init_client(self):
        """Initialize connection to Gemini API."""
        if self._client is None:
            import os
            from openai import OpenAI
            api_key = self.config.glm_api_key or os.environ.get("GEMINI_API_KEY")
            if not api_key:
                raise ValueError(
                    "GEMINI_API_KEY not set. Get a free key at: "
                    "https://aistudio.google.com/apikey\n"
                    "Then set: $env:GEMINI_API_KEY='your_key'"
                )
            self._client = OpenAI(
                base_url=self.config.glm_api_base or "https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=api_key,
            )
    
    def extract_from_pdf(self, pdf_path: Path) -> OCRDocument:
        """Extract text from PDF using GLM-4V vision model."""
        import fitz
        import base64
        import time
        
        self._init_client()
        pdf_path = Path(pdf_path)
        doc = fitz.open(str(pdf_path))
        pages = []
        total_pages = len(doc)
        
        logger.info(f"Processing {total_pages} pages with Gemini 2.0 Flash (~3-8 sec/page)...")
        
        for page_num in range(total_pages):
            page = doc[page_num]
            
            # Render page to image at 200 DPI
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            img_b64 = base64.b64encode(img_bytes).decode("utf-8")
            
            # Call vision model
            start_time = time.time()
            logger.info(f"  Page {page_num + 1}/{total_pages} - sending to Gemini...")
            lines = self._extract_page_with_glm(img_b64, page_num + 1, page)
            elapsed = time.time() - start_time
            logger.info(f"  Page {page_num + 1}/{total_pages} - done ({elapsed:.1f}s, {len(lines)} lines)")
            
            ocr_page = OCRPage(
                page_num=page_num + 1,
                width=page.rect.width,
                height=page.rect.height,
                lines=lines
            )
            pages.append(ocr_page)
        
        doc.close()
        
        return OCRDocument(
            file_path=str(pdf_path),
            pages=pages,
            total_pages=len(pages)
        )
    
    def _extract_page_with_glm(self, img_b64: str, page_num: int, page) -> list:
        """
        Use GLM-4V to extract text with line-level positioning.
        
        The model is prompted to return structured text preserving:
        - Line order (top to bottom)
        - Indentation (left position)
        - Reading order
        """
        import json
        
        prompt = """Extract ALL text from this legal document page exactly as it appears.
Return a JSON array where each element represents one line of text:
[
  {"text": "line content", "y_position": 0.1, "x_position": 0.05, "indent_level": 0},
  ...
]

Rules:
- Preserve exact Gujarati text without translation
- Maintain reading order (top to bottom, left to right)
- y_position: normalized vertical position (0.0 = top, 1.0 = bottom)
- x_position: normalized horizontal position (0.0 = left, 1.0 = right)
- indent_level: 0 = no indent, 1 = first level, 2 = second level
- Include ALL text: headers, body, numbering, everything
- Do NOT summarize or skip any content
- Return ONLY the JSON array, no other text"""
        
        response = self._client.chat.completions.create(
            model=self.config.glm_model_name or "gemini-2.0-flash",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_b64}"}
                        },
                        {"type": "text", "text": prompt}
                    ]
                }
            ],
            max_tokens=8192,
            temperature=0.1,
        )
        
        raw_text = response.choices[0].message.content.strip()
        
        # Parse JSON response
        lines = []
        try:
            # Handle markdown code blocks in response
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[1].rsplit("```", 1)[0]
            
            line_data = json.loads(raw_text)
            page_height = page.rect.height
            page_width = page.rect.width
            
            for item in line_data:
                text = item.get("text", "").strip()
                if not text:
                    continue
                
                y_norm = item.get("y_position", 0)
                x_norm = item.get("x_position", 0)
                
                # Convert normalized positions to absolute coordinates
                y0 = y_norm * page_height
                x0 = x_norm * page_width
                # Estimate line dimensions
                line_height = 14  # approximate
                text_width = len(text) * 7  # approximate
                
                word = OCRWord(
                    text=text,
                    x0=x0, y0=y0,
                    x1=x0 + text_width, y1=y0 + line_height,
                    confidence=0.95,
                    page_num=page_num
                )
                
                ocr_line = OCRLine(
                    text=text,
                    words=[word],
                    x0=x0, y0=y0,
                    x1=x0 + text_width, y1=y0 + line_height,
                    page_num=page_num
                )
                lines.append(ocr_line)
        
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"GLM-4V JSON parse failed for page {page_num}, "
                          f"falling back to line splitting: {e}")
            # Fallback: split raw text into lines
            lines = self._fallback_parse(raw_text, page_num, page)
        
        # Sort by vertical position
        lines.sort(key=lambda l: (l.y0, l.x0))
        return lines
    
    def _fallback_parse(self, raw_text: str, page_num: int, page) -> list:
        """Fallback parsing when JSON extraction fails."""
        lines = []
        page_height = page.rect.height
        text_lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
        
        for idx, text in enumerate(text_lines):
            y0 = (idx / max(len(text_lines), 1)) * page_height
            x0 = 50.0  # default margin
            
            word = OCRWord(
                text=text, x0=x0, y0=y0,
                x1=x0 + len(text) * 7, y1=y0 + 14,
                confidence=0.85, page_num=page_num
            )
            ocr_line = OCRLine(
                text=text, words=[word],
                x0=x0, y0=y0,
                x1=x0 + len(text) * 7, y1=y0 + 14,
                page_num=page_num
            )
            lines.append(ocr_line)
        
        return lines


class PyMuPDFExtractor:
    """
    PyMuPDF-based text extraction (for digitally-born PDFs).
    Faster than OCR but only works if PDF has embedded text.
    """
    
    def __init__(self, config):
        self.config = config
    
    def extract_from_pdf(self, pdf_path: Path) -> OCRDocument:
        """Extract text using PyMuPDF's native text extraction."""
        import fitz
        
        pdf_path = Path(pdf_path)
        doc = fitz.open(str(pdf_path))
        pages = []
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            # Get text with position info
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
            
            lines = []
            for block in blocks:
                if block["type"] == 0:  # text block
                    for line in block["lines"]:
                        text = ""
                        words = []
                        for span in line["spans"]:
                            text += span["text"]
                            word = OCRWord(
                                text=span["text"],
                                x0=span["bbox"][0],
                                y0=span["bbox"][1],
                                x1=span["bbox"][2],
                                y1=span["bbox"][3],
                                confidence=1.0,
                                page_num=page_num + 1
                            )
                            words.append(word)
                        
                        if text.strip():
                            bbox = line["bbox"]
                            ocr_line = OCRLine(
                                text=text.strip(),
                                words=words,
                                x0=bbox[0], y0=bbox[1],
                                x1=bbox[2], y1=bbox[3],
                                page_num=page_num + 1
                            )
                            lines.append(ocr_line)
            
            lines.sort(key=lambda l: (l.y0, l.x0))
            
            ocr_page = OCRPage(
                page_num=page_num + 1,
                width=page.rect.width,
                height=page.rect.height,
                lines=lines
            )
            pages.append(ocr_page)
        
        doc.close()
        
        return OCRDocument(
            file_path=str(pdf_path),
            pages=pages,
            total_pages=len(pages)
        )


class OCRExtractor:
    """
    Unified OCR extraction interface.
    
    Strategy:
    1. Check if PDF has valid Unicode Gujarati text → PyMuPDF native extraction
    2. Otherwise (scanned OR legacy-font-encoded) → GLM-OCR vision model
    
    Many Gujarati court PDFs use legacy non-Unicode fonts (custom glyph mappings)
    which produce garbled text with PyMuPDF. These must be treated as images
    and processed through the vision model.
    """
    
    def __init__(self, config):
        self.config = config
        self.glm_extractor = GLMOCRExtractor(config)
        self.pymupdf_extractor = PyMuPDFExtractor(config)
    
    def _has_valid_unicode_text(self, pdf_path: Path) -> bool:
        """
        Check if PDF has valid Unicode Gujarati/English text.
        
        Legacy Gujarati fonts use ASCII codepoints mapped to Gujarati glyphs,
        producing garbled output when extracted. We detect this by checking
        if extracted text contains actual Gujarati Unicode range (U+0A80-U+0AFF)
        or readable English.
        """
        import fitz
        doc = fitz.open(str(pdf_path))
        has_valid_text = False
        
        for i in range(min(3, len(doc))):
            text = doc[i].get_text().strip()
            if len(text) < 50:
                continue
            
            # Check for Gujarati Unicode characters (U+0A80 to U+0AFF)
            gujarati_chars = sum(1 for c in text if '\u0A80' <= c <= '\u0AFF')
            # Check for readable English (common legal words)
            english_words = sum(1 for w in ['court', 'order', 'application', 'petition',
                                            'respondent', 'applicant', 'advocate', 'judge']
                               if w in text.lower())
            
            # Valid if we find Gujarati Unicode OR meaningful English
            if gujarati_chars > 20 or english_words >= 2:
                has_valid_text = True
                break
        
        doc.close()
        return has_valid_text
    
    def extract(self, pdf_path: Path) -> OCRDocument:
        """
        Extract text from PDF.
        
        - Valid Unicode PDF → PyMuPDF native extraction (fast)
        - Legacy font / scanned PDF → GLM-OCR vision model (accurate)
        """
        pdf_path = Path(pdf_path)
        
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        
        if self._has_valid_unicode_text(pdf_path):
            logger.info(f"Using native text extraction for: {pdf_path.name}")
            return self.pymupdf_extractor.extract_from_pdf(pdf_path)
        
        logger.info(f"Using Gemini Vision OCR for: {pdf_path.name} "
                    f"(legacy font encoding or scanned)")
        return self.glm_extractor.extract_from_pdf(pdf_path)
