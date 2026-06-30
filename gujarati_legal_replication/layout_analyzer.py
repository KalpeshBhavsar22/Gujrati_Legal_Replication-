"""
Layout Understanding Module

Detects headers, section boundaries, paragraph grouping,
numbering extraction, and layout segmentation from OCR output.

Extended with three layout capture modes:
  Option 1 - Visual PNG overlay: draws colored bounding boxes per block type on page images
  Option 2 - Table extraction: uses pdfplumber to find and extract tables per page
  Option 3 - Layout JSON export: dumps full spatial map (block type, bbox, text, indent) to JSON
"""

import re
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List

from .ocr_extractor import OCRDocument, OCRLine, OCRPage

logger = logging.getLogger(__name__)


# Color map for block types used in visual overlay (RGB tuples)
BLOCK_COLOR_MAP = {
    "header":        (255, 50,  50),   # red
    "subheader":     (255, 165,  0),   # orange
    "paragraph":     (50,  150, 255),  # blue
    "numbered_item": (50,  200,  50),  # green
    "table":         (180,   0, 255),  # purple
    "signature":     (255, 220,   0),  # yellow
    "blank":         (180, 180, 180),  # grey
}


@dataclass
class LayoutBlock:
    """A detected layout block (header, paragraph, table, etc.)."""
    block_type: str  # "header", "subheader", "paragraph", "numbered_item", "table", "signature", "blank"
    lines: list      # List[OCRLine]
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page_num: int
    indent_level: int = 0
    numbering: Optional[str] = None  # e.g., "(1)", "(1.1)"
    font_size_estimate: float = 0.0


@dataclass
class LayoutSection:
    """A logical section detected from layout analysis."""
    section_type: str  # "court_header", "case_info", "party_info", "body_section", "order", "signature"
    title: Optional[str] = None
    blocks: list = field(default_factory=list)  # List[LayoutBlock]
    page_start: int = 0
    page_end: int = 0
    numbering: Optional[str] = None


@dataclass
class LayoutAnalysis:
    """Complete layout analysis of a document."""
    sections: list           # List[LayoutSection]
    page_count: int
    detected_headers: list   # List[str]
    numbering_hierarchy: list  # detected numbering patterns
    tables: list = field(default_factory=list)  # Option 2: List of extracted table dicts


class LayoutAnalyzer:
    """
    Analyzes OCR output to detect document structure:
    - Headers and subheaders
    - Section boundaries
    - Numbering hierarchy
    - Paragraph grouping
    - Tables (via pdfplumber)

    Extended outputs:
    - Visual PNG overlays per page  (Option 1)
    - pdfplumber table extraction   (Option 2)
    - Full layout JSON spatial map  (Option 3)
    """

    def __init__(self, config):
        self.config = config
        self.min_section_gap = config.min_section_gap
        self.header_threshold = config.header_font_size_threshold

        # Gujarati court header patterns
        self.court_header_patterns = [
            r"ગુજરાત\s*હાઈકોર્ટ",
            r"HIGH\s*COURT\s*OF\s*GUJARAT",
            r"જિલ્લા\s*ન્યાયાલય",
            r"DISTRICT\s*COURT",
            r"સિવિલ\s*કોર્ટ",
            r"CIVIL\s*COURT",
            r"ગુજરાત\s*સરકાર",
            r"મહેસૂલ\s*વિભાગ",
            r"REVENUE\s*DEPARTMENT",
            r"SECRETARY\s*TO\s*GOVT",
            r"કલેક્ટર\s*(કચેરી|શ્રી)",
        ]

        # Case info patterns
        self.case_info_patterns = [
            r"(સ્પેશિયલ\s*સિવિલ\s*અરજી|SPECIAL\s*CIVIL\s*APPLICATION)",
            r"(રિટ\s*પિટિશન|WRIT\s*PETITION)",
            r"(ફર્સ્ટ\s*અપીલ|FIRST\s*APPEAL)",
            r"(નંબર|NO\.?|No\.?)\s*\d+",
            r"\d{4}",  # year
        ]

        # Section title patterns (Gujarati + English)
        self.section_title_patterns = [
            r"^-?\s*:?\s*(હુકમ|આદેશ|ORDER)\s*:?\s*-?\s*$",
            r"^(હકીકત|FACTS)\s*:?\s*-?\s*$",
            r"^(દલીલ|દલીલો|ARGUMENTS?)\s*:?\s*-?\s*$",
            r"^(અવલોકન|અવલોકનો|OBSERVATIONS?)\s*:?\s*-?\s*$",
            r"^(તારણ|તારણો|FINDINGS?)\s*:?\s*-?\s*$",
            r"^(સંદર્ભ|REFERENCES?)\s*:?\s*-?\s*$",
            r"^(નિર્ણય|JUDGEMENT|JUDGMENT)\s*:?\s*-?\s*$",
            r"^આરજીદારશ્રી\s*:?\s*-?\s*$",
            r"^અરજદાર(શ્રી)?\s*:?\s*-?\s*$",
            r"^સમાવ(ા)?ળા\s*:?\s*-?\s*$",
            r"^સમાવરણ\s*:?\s*-?\s*$",
            r"^વિરુદ્ધ\s*$",
            r"^પ્રતિ\s*,?\s*$",
            r"^વિષય\s*:?\s*-?\s*$",
            r"^વાઘયુક્ત\s*હુકમ\s*:?\s*-?",
            r"^વાઇરસ્ય\s*યુક્ય\s*:?\s*-?",
        ]

        # Numbering patterns
        self.numbering_patterns = [
            (r"^\((\d+)\)\s*", "parenthesized"),
            (r"^\((\d+\.\d+)\)\s*", "sub_paren"),
            (r"^(\d+)\.\s+", "dotted"),
            (r"^(\d+\.\d+)\.\s*", "sub_dotted"),
            (r"^([અ-ૐ])\)\s*", "gujarati_alpha"),
        ]

    # =========================================================================
    # MAIN ENTRY POINT
    # =========================================================================

    def analyze(
        self,
        ocr_doc: OCRDocument,
        pdf_path: Optional[Path] = None,
        overlay_dir: Optional[Path] = None,
        layout_json_dir: Optional[Path] = None,
        table_json_dir: Optional[Path] = None,
    ) -> LayoutAnalysis:
        """
        Perform full layout analysis on OCR document.

        Args:
            ocr_doc: OCR output from ocr_extractor
            pdf_path: original PDF path — required for Option 1 overlay and Option 2 tables
            overlay_dir: directory to save PNG overlays (Option 1)
            layout_json_dir: directory to save layout JSON (Option 3)
            table_json_dir: directory to save table JSON (Option 2)
        """
        all_blocks = []

        for page in ocr_doc.pages:
            page_blocks = self._detect_blocks(page)
            all_blocks.extend(page_blocks)

        sections = self._group_into_sections(all_blocks)
        headers = [s.title for s in sections if s.title]
        numbering = self._extract_numbering_hierarchy(all_blocks)

        # Option 2: Table extraction via pdfplumber
        tables = []
        if pdf_path and table_json_dir:
            tables = self._extract_tables_pdfplumber(pdf_path, table_json_dir)

        layout = LayoutAnalysis(
            sections=sections,
            page_count=ocr_doc.total_pages,
            detected_headers=headers,
            numbering_hierarchy=numbering,
            tables=tables,
        )

        # Option 1: Visual PNG overlay
        if pdf_path and overlay_dir:
            self._save_visual_overlays(pdf_path, all_blocks, overlay_dir)

        # Option 3: Layout JSON export
        if layout_json_dir:
            self._save_layout_json(all_blocks, sections, pdf_path, layout_json_dir)

        return layout

    # =========================================================================
    # OPTION 1: VISUAL BOUNDING BOX OVERLAY
    # =========================================================================

    def _save_visual_overlays(
        self,
        pdf_path: Path,
        all_blocks: list,
        overlay_dir: Path,
    ):
        """
        Render each PDF page as a PNG and draw colored bounding boxes
        for every detected layout block. Each block type gets its own color.
        Saves one PNG per page to overlay_dir.
        """
        try:
            import fitz
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            logger.warning("PyMuPDF or Pillow not available — skipping visual overlays.")
            return

        overlay_dir.mkdir(parents=True, exist_ok=True)
        pdf_stem = Path(pdf_path).stem

        doc = fitz.open(str(pdf_path))

        # Group blocks by page
        blocks_by_page: dict = {}
        for block in all_blocks:
            blocks_by_page.setdefault(block.page_num, []).append(block)

        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_num = page_idx + 1

            # Render at 150 DPI for readable output without huge file size
            dpi = 150
            scale = dpi / 72.0
            pix = page.get_pixmap(dpi=dpi)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            draw = ImageDraw.Draw(img, "RGBA")

            page_width_pt = page.rect.width
            page_height_pt = page.rect.height

            page_blocks = blocks_by_page.get(page_num, [])

            for block in page_blocks:
                color = BLOCK_COLOR_MAP.get(block.block_type, (100, 100, 100))
                rgba_fill = color + (30,)   # semi-transparent fill
                rgba_outline = color + (220,)  # solid outline

                # Scale coordinates from PDF points to pixel space
                x0_px = block.x0 * scale
                y0_px = block.y0 * scale
                x1_px = block.x1 * scale
                y1_px = block.y1 * scale

                # Clamp to image bounds
                x0_px = max(0, min(x0_px, pix.width))
                y0_px = max(0, min(y0_px, pix.height))
                x1_px = max(x0_px + 4, min(x1_px, pix.width))
                y1_px = max(y0_px + 4, min(y1_px, pix.height))

                draw.rectangle([x0_px, y0_px, x1_px, y1_px], fill=rgba_fill)
                draw.rectangle([x0_px, y0_px, x1_px, y1_px], outline=rgba_outline, width=2)

                # Label the block type in small text at top-left of box
                label = block.block_type[:8]
                draw.text((x0_px + 2, y0_px + 1), label, fill=color + (255,))

            # Draw legend in bottom-right corner
            legend_x = pix.width - 160
            legend_y = pix.height - (len(BLOCK_COLOR_MAP) * 18 + 10)
            draw.rectangle(
                [legend_x - 5, legend_y - 5, pix.width - 2, pix.height - 2],
                fill=(255, 255, 255, 200)
            )
            for i, (btype, color) in enumerate(BLOCK_COLOR_MAP.items()):
                y = legend_y + i * 18
                draw.rectangle([legend_x, y, legend_x + 14, y + 12], fill=color + (220,))
                draw.text((legend_x + 18, y), btype, fill=(30, 30, 30, 255))

            out_path = overlay_dir / f"{pdf_stem}_page_{page_num:02d}_overlay.png"
            img.save(str(out_path), "PNG")
            logger.info(f"  Saved overlay: {out_path.name}")

        doc.close()
        logger.info(f"Option 1: Visual overlays saved to {overlay_dir}")

    # =========================================================================
    # OPTION 2: TABLE EXTRACTION VIA PDFPLUMBER
    # =========================================================================

    def _extract_tables_pdfplumber(
        self,
        pdf_path: Path,
        table_json_dir: Path,
    ) -> list:
        """
        Use pdfplumber to detect and extract tables from each page.
        Saves a JSON file per PDF with all tables found.
        Returns a list of table dicts.
        """
        try:
            import pdfplumber
        except ImportError:
            logger.warning("pdfplumber not available — skipping table extraction.")
            return []

        table_json_dir.mkdir(parents=True, exist_ok=True)
        pdf_stem = Path(pdf_path).stem
        all_tables = []

        with pdfplumber.open(str(pdf_path)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                raw_tables = page.extract_tables()
                if not raw_tables:
                    continue

                for table_idx, raw_table in enumerate(raw_tables):
                    # Clean None values
                    cleaned = [
                        [cell if cell is not None else "" for cell in row]
                        for row in raw_table
                    ]

                    # Try to get bounding box of the table
                    try:
                        table_settings = {}
                        found = page.find_tables(table_settings)
                        bbox = found[table_idx].bbox if table_idx < len(found) else None
                    except Exception:
                        bbox = None

                    table_record = {
                        "page": page_num,
                        "table_index": table_idx,
                        "bbox": list(bbox) if bbox else None,
                        "rows": len(cleaned),
                        "cols": max((len(r) for r in cleaned), default=0),
                        "data": cleaned,
                    }
                    all_tables.append(table_record)
                    logger.info(
                        f"  Page {page_num}: table {table_idx} "
                        f"({table_record['rows']} rows x {table_record['cols']} cols)"
                    )

        out_path = table_json_dir / f"{pdf_stem}_tables.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(all_tables, f, ensure_ascii=False, indent=2)

        logger.info(f"Option 2: {len(all_tables)} tables saved to {out_path.name}")
        return all_tables

    # =========================================================================
    # OPTION 3: LAYOUT JSON EXPORT
    # =========================================================================

    def _save_layout_json(
        self,
        all_blocks: list,
        sections: list,
        pdf_path: Optional[Path],
        layout_json_dir: Path,
    ):
        """
        Export the full spatial layout map as a JSON file.
        Contains every block with: type, page, bbox, indent, numbering, text.
        Also contains section groupings with their blocks.
        """
        layout_json_dir.mkdir(parents=True, exist_ok=True)
        pdf_stem = Path(pdf_path).stem if pdf_path else "document"

        # Serialize all blocks
        blocks_data = []
        for block in all_blocks:
            blocks_data.append({
                "block_type": block.block_type,
                "page": block.page_num,
                "bbox": {
                    "x0": round(block.x0, 2),
                    "y0": round(block.y0, 2),
                    "x1": round(block.x1, 2),
                    "y1": round(block.y1, 2),
                },
                "indent_level": block.indent_level,
                "numbering": block.numbering,
                "font_size_estimate": round(block.font_size_estimate, 2),
                "text": block.text,
            })

        # Serialize sections with their block references
        sections_data = []
        for section in sections:
            section_blocks = []
            for block in section.blocks:
                section_blocks.append({
                    "block_type": block.block_type,
                    "page": block.page_num,
                    "bbox": {
                        "x0": round(block.x0, 2),
                        "y0": round(block.y0, 2),
                        "x1": round(block.x1, 2),
                        "y1": round(block.y1, 2),
                    },
                    "indent_level": block.indent_level,
                    "numbering": block.numbering,
                    "text": block.text,
                })
            sections_data.append({
                "section_type": section.section_type,
                "title": section.title,
                "page_start": section.page_start,
                "page_end": section.page_end,
                "block_count": len(section.blocks),
                "blocks": section_blocks,
            })

        output = {
            "source_pdf": str(pdf_path) if pdf_path else "",
            "total_blocks": len(all_blocks),
            "total_sections": len(sections),
            "block_type_counts": self._count_block_types(all_blocks),
            "blocks": blocks_data,
            "sections": sections_data,
        }

        out_path = layout_json_dir / f"{pdf_stem}_layout.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        logger.info(f"Option 3: Layout JSON saved to {out_path.name}")

    def _count_block_types(self, all_blocks: list) -> dict:
        counts = {}
        for block in all_blocks:
            counts[block.block_type] = counts.get(block.block_type, 0) + 1
        return counts

    # =========================================================================
    # CORE BLOCK DETECTION (unchanged logic, same as original)
    # =========================================================================

    def _detect_blocks(self, page: OCRPage) -> list:
        """Detect layout blocks within a page."""
        blocks = []
        current_block_lines = []
        prev_line = None

        for line in page.lines:
            if prev_line and self._is_new_block(prev_line, line, page):
                if current_block_lines:
                    block = self._classify_block(current_block_lines, page.page_num)
                    blocks.append(block)
                current_block_lines = [line]
            else:
                current_block_lines.append(line)
            prev_line = line

        if current_block_lines:
            block = self._classify_block(current_block_lines, page.page_num)
            blocks.append(block)

        return blocks

    def _is_new_block(self, prev_line: OCRLine, curr_line: OCRLine, page: OCRPage) -> bool:
        """Determine if current line starts a new block."""
        vertical_gap = curr_line.y0 - prev_line.y1

        if vertical_gap > self.min_section_gap:
            return True

        indent_diff = abs(curr_line.x0 - prev_line.x0)
        if indent_diff > 30:
            return True

        for pattern, _ in self.numbering_patterns:
            if re.match(pattern, curr_line.text):
                return True

        return False

    def _classify_block(self, lines: list, page_num: int) -> LayoutBlock:
        """Classify a group of lines into a block type."""
        full_text = " ".join(l.text for l in lines).strip()

        x0 = min(l.x0 for l in lines)
        y0 = min(l.y0 for l in lines)
        x1 = max(l.x1 for l in lines)
        y1 = max(l.y1 for l in lines)

        avg_height = sum(l.y1 - l.y0 for l in lines) / len(lines)

        block_type = "paragraph"
        numbering = None
        indent_level = 0

        for pattern in self.court_header_patterns:
            if re.search(pattern, full_text, re.IGNORECASE):
                block_type = "header"
                break

        if block_type == "paragraph":
            for pattern in self.section_title_patterns:
                first_line = lines[0].text.strip() if lines else ""
                if re.match(pattern, first_line, re.IGNORECASE):
                    block_type = "subheader"
                    break
                if len(full_text) < 80 and re.match(pattern, full_text.strip(), re.IGNORECASE):
                    block_type = "subheader"
                    break

        if block_type == "paragraph":
            for pattern, num_type in self.numbering_patterns:
                match = re.match(pattern, full_text)
                if match:
                    block_type = "numbered_item"
                    numbering = match.group(0).strip()
                    if "." in (match.group(1) if match.lastindex else ""):
                        indent_level = 1
                    break

        # Detect signature blocks
        if block_type == "paragraph":
            sig_keywords = ["સહી", "સિક્કો", "secretary", "Suseel", "(એલ.પી", "આ.ક.", "judge"]
            if any(kw.lower() in full_text.lower() for kw in sig_keywords):
                block_type = "signature"

        # Indent from x position
        page_left_margin = 50
        if x0 > page_left_margin + 60:
            indent_level = max(indent_level, 1)
        if x0 > page_left_margin + 120:
            indent_level = max(indent_level, 2)

        return LayoutBlock(
            block_type=block_type,
            lines=lines,
            text=full_text,
            x0=x0, y0=y0, x1=x1, y1=y1,
            page_num=page_num,
            indent_level=indent_level,
            numbering=numbering,
            font_size_estimate=avg_height,
        )

    def _group_into_sections(self, blocks: list) -> list:
        """Group blocks into logical sections."""
        sections = []
        current_section = None

        for block in blocks:
            if block.block_type == "header":
                if current_section:
                    sections.append(current_section)
                current_section = LayoutSection(
                    section_type="court_header",
                    title=block.text[:100],
                    blocks=[block],
                    page_start=block.page_num,
                    page_end=block.page_num,
                )

            elif block.block_type == "subheader":
                if current_section:
                    sections.append(current_section)
                current_section = LayoutSection(
                    section_type="body_section",
                    title=block.text.strip(),
                    blocks=[block],
                    page_start=block.page_num,
                    page_end=block.page_num,
                )

            else:
                if current_section is None:
                    section_type = self._infer_section_type(block)
                    current_section = LayoutSection(
                        section_type=section_type,
                        blocks=[block],
                        page_start=block.page_num,
                        page_end=block.page_num,
                    )
                else:
                    current_section.blocks.append(block)
                    current_section.page_end = block.page_num

        if current_section:
            sections.append(current_section)

        return sections

    def _infer_section_type(self, block: LayoutBlock) -> str:
        """Infer section type from block content."""
        text = block.text.lower()
        block_text = block.text

        for pattern in self.case_info_patterns:
            if re.search(pattern, block_text, re.IGNORECASE):
                return "case_info"

        if any(kw in text for kw in ["અરજદાર", "આરજીદાર", "applicant", "petitioner"]):
            return "party_applicant"
        if any(kw in text for kw in ["સામાવાળા", "સમાવરણ", "respondent", "opponent"]):
            return "party_respondent"
        if "વિરુદ્ધ" in text:
            return "versus"
        if any(kw in text for kw in ["હુકમ", "આદેશ", "order"]):
            return "order"
        if any(kw in text for kw in ["હકીકત", "facts"]):
            return "facts"
        if "વિષય" in text:
            return "subject"
        if any(kw in text for kw in ["સચિવ", "secretary", "સહી", "સિક્કો"]):
            return "signature"
        if text.strip().startswith("પ્રતિ"):
            return "distribution"

        return "body_section"

    def _extract_numbering_hierarchy(self, blocks: list) -> list:
        """Extract the numbering patterns used in the document."""
        found_patterns = []
        for block in blocks:
            if block.numbering:
                found_patterns.append({
                    "numbering": block.numbering,
                    "indent_level": block.indent_level,
                    "page": block.page_num,
                })
        return found_patterns