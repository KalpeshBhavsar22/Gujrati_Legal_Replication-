# Structured Gujarati Legal Judgement Replication System

A pipeline that **replicates** the exact format, structure, section order, and court layout of Gujarat Revenue Department legal orders by using a reference document as the structural template.

> **This is NOT a chatbot, QA system, or summarizer.**  
> This is a **Document Format Replicator** — it copies the exact structure of a reference PDF and fills in new case details.

---

## Architecture

```
Reference PDF                    New Case Context (JSON)
     │                                    │
     ▼                                    │
┌─────────────────────┐                   │
│  OCR Extraction     │  PyMuPDF (digital) / Gemini Vision (legacy fonts)
│  (text + coords)    │
└─────────┬───────────┘                   │
          ▼                               │
┌─────────────────────┐                   │
│  Layout Analysis    │  Headers, sections, numbering, indentation
└─────────┬───────────┘                   │
          ▼                               │
┌─────────────────────┐                   │
│  Structured Parser  │  → _parsed.json (typed sections, parties, order)
└─────────┬───────────┘                   │
          │                               │
          ▼                               │
┌─────────────────────┐                   │
│  Raw Text / FAISS   │  Reference format + embeddings (supplementary)
└─────────┬───────────┘                   │
          │                               │
          ▼                               ▼
┌──────────────────────────────────────────────┐
│  FORMAT REPLICATOR (Gemini LLM)              │
│  System: "Replicate this format exactly"     │
│  Input: full reference text + case details   │
│  Output: new document in identical format    │
└─────────────────────┬────────────────────────┘
                      ▼
┌─────────────────────────────────────────┐
│  Context-Aware DOCX Formatter           │
│  Right-aligned: headers, signatures     │
│  Centered: dividers (વિરુદ્ધ, હુકમ)    │
│  Left-aligned: body paragraphs          │
└─────────────────────────────────────────┘
```

---

## Prerequisites

- Python 3.10+
- Google Gemini API key (free tier: 1500 requests/day)
  - Get one at: https://aistudio.google.com/apikey

---

## Installation

```bash
cd gujarati_legal_replication
pip install -r requirements.txt
```

Set your API key:
```bash
# Windows
set GEMINI_API_KEY=your_key_here

# Linux/macOS/Colab
export GEMINI_API_KEY=your_key_here
```

No local GPU or LLM setup required — all inference runs via Google Gemini API.

---

## Usage

### Step 1: Index Reference PDFs (OCR + Parsing)

Place reference judgement PDFs in `data/input_pdfs/`:

```python
from gujarati_legal_replication.config import PipelineConfig
from gujarati_legal_replication.pipeline import JudgementReplicationPipeline

pipeline = JudgementReplicationPipeline(PipelineConfig())

# Full pipeline: OCR → Layout → Structured JSON
pipeline.index_reference_corpus()
# Saves: data/parsed/judgement_X_parsed.json (structured sections)

# Or single PDF with Gemini Vision OCR (for legacy fonts)
pipeline.process_single_pdf("data/input_pdfs/judgement_4.pdf")
# Saves: data/parsed/judgement_4_parsed.json
```

The full pipeline does:
1. **OCR Extraction** — PyMuPDF for digital PDFs, Gemini Vision for legacy/scanned fonts
2. **Layout Analysis** — detects headers, section boundaries, numbering hierarchies, indentation levels
3. **Structured Parsing** — converts layout into typed JSON schema (parties, facts, arguments, order sections with subsections)

For format replication, the raw text is also saved and used directly as the reference template.

### Step 2: Generate New Judgement (Replication Phase)

Create or edit `data/sample_case_context.json` with your case details, then:

```python
import json

case = json.loads(open("data/sample_case_context.json").read())
output = pipeline.generate_judgement(case, output_format="docx")
print(f"Output: {output}")
```

The pipeline automatically loads the first `_raw.txt` file from `data/parsed/` as the format reference.

### Step 3: Formatted DOCX Output

The generated DOCX applies context-aware formatting:
- **Right-aligned:** Government header, address block, date, case number, signature/રાજ્યપાલ formula
- **Centered:** "વિરુદ્ધ" (versus), "-: હુકમ :-" (order divider)
- **Left-aligned:** Body paragraphs, facts, representations, findings
- **Bold:** Section headers, party labels, legal provisions
- **Indented:** Party sub-items, distribution list

---

## Configuration

Edit `config.py`:

| Config | What it controls | Default |
|--------|-----------------|---------|
| `OCRConfig.glm_model_name` | Vision model for OCR | `gemini-2.5-flash` |
| `GenerationConfig.model_name` | Text generation model | `gemini-3.1-flash-lite` |
| `GenerationConfig.temperature` | Creativity (lower = more faithful) | `0.3` |
| `GenerationConfig.max_tokens_per_section` | Output length limit | `8192` |
| `RetrievalConfig.embedding_model` | Embedding model | `gemini-embedding-001` |

**API key** is read from the `GEMINI_API_KEY` environment variable.

---

## Google Colab

This project runs on Google Colab with no changes to the core logic:

```python
!pip install python-docx openai faiss-cpu PyMuPDF

# Set API key via Colab secrets
from google.colab import userdata
import os
os.environ["GEMINI_API_KEY"] = userdata.get("GEMINI_API_KEY")

# Upload PDFs or mount Google Drive
from google.colab import drive
drive.mount('/content/drive')
```

Then update paths in `PipelineConfig` to point to `/content/...` instead of Windows paths.

---

## Sample Case Context

```json
{
  "case_number": "મવિવિ/હકપ/મહે/૮૭/૨૦૨૪",
  "authority": "સંયુક્ત સચિવ",
  "department": "મહેસૂલ વિભાગ",
  "applicant": "રમેશભાઈ પટેલ",
  "respondent": "ગ્રામ પંચાયત, ગામ: XYZ",
  "subject": "જમીન મહેસૂલ અધિનિયમ કલમ ૬૫ અંતર્ગત અપીલ",
  "outcome": "અંશત: મંજુર + રીમાન્ડ",
  "facts_summary": "Brief facts...",
  "order_details": "Order specifics..."
}
```

---

## Key Design Principles

| Wrong Approach | This System |
|---------------|-------------|
| AI invents document structure | Copies reference structure exactly |
| Free-form generation | "REPLICATE THIS FORMAT" prompt |
| Section-by-section with template | Single-pass full-document replication |
| Local LLM on limited GPU | Cloud API (free tier, high quality) |
| RAG semantic chunking | Full reference document as context |
| Generic DOCX output | Content-aware alignment detection |

---

## Project Structure

```
gujarati_legal_replication/
├── __init__.py              # Package init
├── __main__.py              # CLI entry point
├── config.py                # All configuration (models, paths, API)
├── ocr_extractor.py         # Phase 1: OCR (PyMuPDF native + Gemini Vision)
├── layout_analyzer.py       # Phase 2: Section/header/numbering detection
├── structured_parser.py     # Phase 3: → typed JSON schema (_parsed.json)
├── template_learner.py      # Phase 4: Template learning (unused in replication mode)
├── section_retriever.py     # FAISS retrieval (supplementary)
├── constrained_generator.py # FORMAT REPLICATOR (core generation)
├── document_reconstructor.py# DOCX formatting
├── pipeline.py              # Main orchestrator
├── ADR.md                   # Architecture Decision Records
├── requirements.txt         # Dependencies
└── data/
    ├── sample_case_context.json  # Example case input
    ├── input_pdfs/               # Reference judgement PDFs
    ├── parsed/                   # _parsed.json (structured) + _raw.txt (raw OCR)
    ├── vector_index/             # FAISS index (supplementary)
    └── output/                   # Generated .docx and .txt files
```

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| PDF Rendering | PyMuPDF (fitz) |
| OCR | Google Gemini Vision API |
| Embeddings | gemini-embedding-001 (3072-dim) |
| Vector Store | FAISS (flat, AVX2) |
| Generation | gemini-3.1-flash-lite |
| LLM Interface | OpenAI-compatible API |
| Document Output | python-docx |
| Language | Python 3.13 |

---

## What Gets Preserved

- ✅ Government header block (right-aligned)
- ✅ Case number and date formatting
- ✅ Party/applicant/respondent block structure
- ✅ Section ordering (facts → representations → collector's order → observations → હુકમ)
- ✅ Gujarati numbering hierarchy: (૧), (૧.૧), (૧.૨), (૨)...
- ✅ Legal Gujarati terminology and register
- ✅ "રાજ્યપાલશ્રીના હુકમથી" signature formula
- ✅ Distribution list (નકલ રવાના)
- ✅ Centered dividers (વિરુદ્ધ, -: હુકમ :-)
- ✅ Revenue Department administrative order style (NOT High Court judgement style)

---

## Rate Limits (Free Tier)

| Resource | Limit |
|----------|-------|
| Gemini Vision (OCR) | 15 RPM, 1500 RPD |
| Gemini Text (generation) | ~20 RPD per model |
| Gemini Embeddings | 1500 RPD |

Multiple models available for rotation when limits are hit: gemini-2.5-flash, gemini-2.5-flash-lite, gemini-2.0-flash, gemini-3.1-flash-lite.
