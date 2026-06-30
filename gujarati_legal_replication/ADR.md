# Architecture Decision Records (ADR)

## Structured Gujarati Legal Judgement Replication System

---

## ADR-001: System Classification — Document Format Replication, Not RAG/QA

**Status:** Accepted  
**Date:** 2024-03-15  
**Updated:** 2026-05-19  
**Context:**  
Traditional approaches treat legal document generation as a RAG problem — chunk documents, embed them, retrieve similar chunks, and let an LLM generate freely. This destroys legal formatting, numbering hierarchies, and court layout conventions.

Initial implementation confirmed that section-by-section generation with learned templates still produces High Court-style output with AI-invented sections when the references are simple Revenue Department administrative orders.

**Decision:**  
Classify this system as a **Document Format Replicator** — the LLM acts as a format-copying machine, not a legal reasoning engine. A specific reference document is passed in full, and the model replicates its exact structure with new case details.

**Consequences:**  
- No free-form generation — the model is explicitly told "REPLICATE THIS FORMAT EXACTLY"
- No section-by-section generation (single-pass replication is sufficient for 5-8 page documents)
- Evaluation is visual: does the output look like the input PDF?
- System prompt is "FORMAT REPLICATOR for Gujarat Revenue Department legal orders"

---

## ADR-002: OCR Strategy — Google Gemini Vision API

**Status:** Superseded → Revised  
**Date:** 2024-03-15  
**Updated:** 2026-05-19  
**Context:**  
Original plan: GLM-4V (Zhipu AI) primary, PaddleOCR fallback. In practice:
1. Reference PDFs use **legacy non-Unicode Gujarati fonts** — PyMuPDF text extraction returns garbled output
2. GLM-4V via Ollama (haervwe/GLM-4.6V-Flash-9B) was too slow on RTX A1000 6GB
3. PaddleOCR was never installed — Gemini Vision proved superior

**Decision:**  
Use **Google Gemini Vision API** (gemini-3.1-flash-lite) for OCR:
- PDF pages rendered to images via PyMuPDF, then sent to Gemini Vision
- Single API call per page with prompt: "Extract all Gujarati text exactly as written"
- Output saved as `{filename}_raw.txt` in `data/parsed/`

**Rationale:**

| Criterion | Gemini Vision | GLM-4V (local) | PyMuPDF text |
|-----------|--------------|----------------|--------------|
| Legacy font handling | Excellent (image-based) | Excellent | Fails completely |
| Speed | ~2-3s/page | ~30s+/page (6GB GPU) | Instant but useless |
| Cost | Free tier (1500 RPD) | Free (local) | Free |
| Gujarati accuracy | Very high | High | N/A for legacy fonts |
| Setup | API key only | 9B model download + GPU | Built-in |

**Consequences:**  
- Requires Google Gemini API key (free tier sufficient for development)
- Network dependency for OCR (no offline fallback currently)
- Excellent handling of legacy non-Unicode Gujarati fonts
- Rate limits: 15 RPM, 1500 RPD on free tier

**Models tried and rejected:**
- Ollama GLM-4V-Flash-9B: Too slow on 6GB VRAM
- Ollama minicpm-v: Failed to download
- PyMuPDF native text extraction: Returns garbage for legacy fonts
- PaddleOCR: Never tested — Gemini solved the problem first

---

## ADR-003: Layout Understanding — Implicit via Vision Model

**Status:** Superseded → Revised  
**Date:** 2024-03-15  
**Updated:** 2026-05-19  
**Context:**  
Original plan: rule-based spatial analysis with vertical gaps, X-positions, font sizes. In practice, Gemini Vision OCR preserves reading order and implicit structure from the page image.

**Decision:**  
Layout understanding is handled **implicitly** by the Vision model during OCR. The raw text output preserves:
- Line breaks and paragraph structure
- Relative positioning (headers vs body)
- Numbering hierarchies as written

Explicit layout analysis (PyMuPDF spatial coordinates) is used only for DOCX formatting — detecting which lines should be right-aligned, centered, or left-aligned based on content patterns.

**Consequences:**  
- No separate "layout analysis" phase needed
- OCR output is the de facto structured intermediate representation
- DOCX formatting uses content-aware heuristics (regex patterns for government headers, signatures, dividers)

---

## ADR-004: Intermediate Representation — Raw Text, Not JSON Schema

**Status:** Superseded → Revised  
**Date:** 2024-03-15  
**Updated:** 2026-05-19  
**Context:**  
Original plan: typed JSON schema with sections, subsections, numbering fields. In practice, the format replication approach works directly with raw text — the full reference document is passed to the LLM as-is.

**Decision:**  
The intermediate representation is **plain text** (`*_raw.txt` files). The JSON schema infrastructure still exists in code but is bypassed during generation:
- OCR produces raw text → saved to `data/parsed/{name}_raw.txt`
- Generation reads raw text directly as `reference_text`
- Output is raw text → formatted into DOCX

**Consequences:**  
- Simpler pipeline — no parsing errors or schema mismatches
- Full document fidelity preserved (no information lost to schema mapping)
- Existing JSON schema code remains for potential future structured analysis

---

## ADR-005: Retrieval Strategy — FAISS with Gemini Embeddings (Supporting Role)

**Status:** Revised  
**Date:** 2024-03-15  
**Updated:** 2026-05-19  
**Context:**  
Original plan: section-type-aware FAISS indices with multilingual-e5-large. In practice, the format replication approach passes the full reference document directly, making retrieval optional/supplementary.

**Decision:**  
FAISS index exists and is built from parsed sections using **gemini-embedding-001** (3072 dimensions). It serves as supplementary context but the primary generation mechanism is direct reference text injection.

**Current implementation:**
- Embedding model: `gemini-embedding-001` via Google Generative AI REST API
- Dimensions: 3072
- Index: Single FAISS flat index (not per-section-type)
- Role: Provides additional context if reference_text is unavailable; otherwise bypassed

**Consequences:**  
- FAISS is built but rarely the primary driver of generation quality
- gemini-embedding-001 is free and high-quality for Gujarati
- Index can be expanded as more documents are parsed

---

## ADR-006: Embedding Model — gemini-embedding-001

**Status:** Superseded → Revised  
**Date:** 2024-03-15  
**Updated:** 2026-05-19  
**Context:**  
Original plan: multilingual-e5-large (1024-dim, local). Switched to Gemini embeddings for consistency with the rest of the API stack and superior Gujarati performance.

**Decision:**  
Use `gemini-embedding-001` via Google Generative AI API:
- 3072 dimensions
- Free tier: 1500 RPD
- Excellent multilingual/Gujarati support
- No local model download required

**Alternatives Rejected:**
- `multilingual-e5-large`: Would require local GPU memory (already constrained at 6GB)
- OpenAI `text-embedding-3-large`: Paid API, no advantage over free Gemini
- Local sentence-transformers: VRAM budget exhausted by other needs

---

## ADR-007: Generation Strategy — Single-Pass Format Replication

**Status:** Superseded → Revised  
**Date:** 2024-03-15  
**Updated:** 2026-05-19  
**Context:**  
Original plan: section-by-section generation with template constraints. In testing, this approach produced AI-invented structures (High Court style with "Arguments", "Observations" sections) when references were simple 5-page Revenue Department orders.

The core insight: **the model should not decide document structure — it should copy it exactly from a reference.**

**Decision:**  
Single-pass generation with full reference text:
1. Load full reference document text (e.g., `judgement_4_raw.txt`, ~6000 chars)
2. System prompt: "You are a FORMAT REPLICATOR for Gujarat Revenue Department legal orders"
3. User prompt: "Here is the reference document. REPLICATE THIS FORMAT EXACTLY with the following new case details: [case_context]"
4. Model outputs full document in one call (max_tokens=8192)

**Key constraints in the prompt:**
- "DO NOT add any section headers, structure, or formatting that does NOT exist in the reference"
- "DO NOT use High Court format, advocate arguments, or judicial observations unless they appear in the reference"
- "MATCH the exact numbering style, section ordering, and closing formula"

**Consequences:**  
- Output structure is deterministic (copies reference exactly)
- Only one LLM call per document (fast, cheap)
- Works well for 5-8 page Revenue Department orders
- May need section-by-section approach for longer documents (20+ pages) in future

---

## ADR-008: Generation Model — Google Gemini (Free Tier)

**Status:** Superseded → Revised  
**Date:** 2024-03-15  
**Updated:** 2026-05-19  
**Context:**  
Original plan: Qwen2.5-7B via local Ollama/vLLM. In practice:
- RTX A1000 6GB cannot run 7B+ models at acceptable speed
- Gujarati generation quality from small local models was poor
- Google Gemini free tier provides superior quality at zero cost

**Decision:**  
Use **Google Gemini API** (OpenAI-compatible endpoint) for generation:
- Current model: `gemini-3.1-flash-lite`
- Temperature: 0.3 (low creativity, high fidelity)
- Max tokens: 8192
- API base: `https://generativelanguage.googleapis.com/v1beta/openai/`

**Model selection journey:**
1. GLM-4V-Flash-9B (Ollama) — too slow for generation
2. gemini-2.5-flash — works well, 20 req/day limit
3. gemini-2.5-flash-lite — works well, 20 req/day limit
4. gemini-2.0-flash — works well, 20 req/day limit
5. **gemini-3.1-flash-lite** — current choice, adequate quota remaining

**Rate limit management:** Multiple models available for rotation when one exhausts daily quota.

**Consequences:**  
- Cloud dependency (not local-first as originally planned)
- Free tier is sufficient for development/low-volume use
- Quality is significantly better than any local model on 6GB GPU
- Daily quota limits require model rotation or upgrading to paid tier for production

---

## ADR-009: Output Format — Context-Aware DOCX with Court Layout

**Status:** Revised  
**Date:** 2024-03-15  
**Updated:** 2026-05-19  
**Context:**  
Original plan was correct (DOCX via python-docx) but the formatting logic needed to match the specific reference PDF layout — Gujarat Revenue Department orders, not High Court judgements.

**Decision:**  
Generate DOCX using `python-docx` with **content-aware alignment detection**:
- Page: A4 (8.27" × 11.69")
- Margins: 1.0" left, 0.5" right, 0.5" top/bottom
- Font: Shruti, 11pt body / 12pt headers
- **Right-aligned:** Government header block, address, date, case number, signature block, "રાજ્યપાલ" formula
- **Centered:** "વિરુદ્ધ" (versus), "-: હુકમ :-" (order divider)
- **Left-aligned:** Body paragraphs, facts, representations, findings
- **Indented:** Party sub-items, distribution list items

Detection is regex-based on Gujarati content patterns (government keywords, signature markers, divider patterns).

**Output formats supported:**
- `.docx` — primary, with full formatting
- `.txt` — plain text for preview/validation

**Consequences:**  
- Output visually matches reference PDFs
- Formatting adapts to content (not fixed template positions)
- Shruti font ships with Windows (no installation needed)
- Edge cases: some section headers may be mis-classified (e.g., "(સહી)" detection)

---

## ADR-010: Template Learning — Deprecated (Format Replication Instead)

**Status:** Deprecated  
**Date:** 2024-03-15  
**Updated:** 2026-05-19  
**Context:**  
Statistical template learning was designed but never implemented. The format replication approach (passing full reference text) eliminates the need for learned templates — the reference document IS the template.

**Decision:**  
Template learning infrastructure exists in code (`TemplateLearner` class) but is effectively bypassed. The pipeline:
1. Loads a reference `_raw.txt` file directly
2. Passes it to the generator as `reference_text`
3. No statistical analysis needed

**Consequences:**  
- Simpler system — one reference document drives the format
- No corpus analysis step required
- To change output style, simply point to a different reference PDF
- Template learner code can be removed or activated later if multi-style support is needed

---

## ADR-011: Pipeline Mode — Replicate Only (Simplified)

**Status:** Revised  
**Date:** 2024-03-15  
**Updated:** 2026-05-19  
**Context:**  
Three modes were planned (Index, Generate, Replicate). In practice, only **Replicate** is used — the system takes one specific reference document and generates a new one with identical format.

**Decision:**  
The pipeline operates in two phases:
1. **OCR phase:** Parse reference PDFs → save as `_raw.txt` (done once)
2. **Replicate phase:** Load reference text + case context → generate → format DOCX

The "Index" phase (FAISS building) is optional and supplementary. The "Generate" mode (template-based) is unused.

**Consequences:**  
- Simplified mental model: "pick a reference, generate a replica"
- Adding a new document style = parsing one new reference PDF
- No training/indexing step required for basic operation

---

## ADR-012: Error Handling — API Quota Management

**Status:** Revised  
**Date:** 2024-03-15  
**Updated:** 2026-05-19  
**Context:**  
Original concern: OCR failures, API timeouts, parse failures. Actual primary concern: **Google Gemini free tier rate limits** (20 RPD per model for generation, 1500 RPD for embeddings).

**Decision:**  
- Multiple Gemini models configured for rotation (2.5-flash, 2.5-flash-lite, 2.0-flash, 3.1-flash-lite)
- When one model exhausts quota, switch to another in `config.py`
- Quotas reset daily
- OCR and generation use separate quota pools (vision vs text)

**Fallback chain:**

| Phase | Primary | Fallback |
|-------|---------|----------|
| OCR | gemini-3.1-flash-lite (vision) | Try other Gemini models → wait for quota reset |
| Embedding | gemini-embedding-001 | N/A (1500 RPD sufficient) |
| Generation | gemini-3.1-flash-lite | Rotate to other Gemini models |
| DOCX output | Context-aware formatter | Plain text output |

**Consequences:**  
- System works within free tier constraints
- Manual model rotation when limits hit (could be automated)
- No offline fallback currently (cloud-dependent)

---

## ADR-013: Data Privacy — Cloud-Dependent (Revised)

**Status:** Revised  
**Date:** 2024-03-15  
**Updated:** 2026-05-19  
**Context:**  
Original plan: local-first with no cloud dependencies. This was abandoned due to hardware constraints (6GB VRAM insufficient for quality local models) and the superior results from Gemini API.

**Decision:**  
Accept cloud dependency on Google Gemini API for all LLM operations:
- OCR: pages sent as images to Gemini Vision
- Embeddings: text sent to Gemini Embedding API
- Generation: case context + reference text sent to Gemini

**Mitigations:**
- All data stored locally (FAISS index, parsed text, output)
- No persistent storage on Google's side (API is stateless)
- API key is user-controlled
- For production with sensitive documents, can upgrade to Gemini's enterprise tier with data protection guarantees

**Consequences:**  
- Network required for all LLM operations
- Google processes document content (acceptable for development; review for production)
- Cannot deploy in air-gapped environments without switching to local models
- If privacy requirements change, pipeline is model-agnostic (OpenAI-compatible interface)

---

## ADR-014: Numbering Preservation — Via Format Replication

**Status:** Revised  
**Date:** 2024-03-15  
**Updated:** 2026-05-19  
**Context:**  
Original plan: numbering as a first-class schema element with extraction, storage, validation. In practice, the format replication approach handles this naturally — the LLM copies the reference's numbering style (૧.૧, ૧.૨, ૨.૧, etc.) as part of the full-text replication.

**Decision:**  
Numbering preservation is handled implicitly by the FORMAT REPLICATOR prompt:
- Reference document shows exact numbering style
- Model is told to "MATCH the exact numbering style"
- No separate numbering extraction/validation logic needed

Supported patterns (observed in references):
- `(૧)`, `(૨)` — Gujarati numeral paragraphs
- `(૧.૧)`, `(૧.૨)` — sub-paragraphs
- `૧.`, `૨.` — distribution lists
- `-: હુકમ :-` — order section divider

**Consequences:**  
- Numbering accuracy depends on LLM's ability to follow format instructions
- No programmatic validation (could be added as post-processing)
- Works well in practice for 5-8 page documents

---

## ADR-015: Technology Stack Summary (Actual)

**Status:** Revised  
**Date:** 2024-03-15  
**Updated:** 2026-05-19

| Layer | Technology | Role |
|-------|-----------|------|
| PDF Rendering | PyMuPDF (fitz) | Convert PDF pages to images for Vision OCR |
| OCR | Google Gemini Vision (gemini-3.1-flash-lite) | Extract Gujarati text from page images |
| Layout Analysis | Content-aware regex heuristics | Detect alignment patterns for DOCX formatting |
| Intermediate Format | Plain text (`_raw.txt`) | Preserved OCR output as reference |
| Embeddings | gemini-embedding-001 (3072-dim) | Section vectorization (supplementary) |
| Vector Store | FAISS (flat, AVX2) | Similarity search (supplementary) |
| Generation | gemini-3.1-flash-lite | Single-pass format replication |
| LLM Interface | OpenAI-compatible (google generativelanguage API) | Unified API access |
| Document Output | python-docx | Context-aware formatted DOCX |
| Language | Python 3.13 | Implementation |
| Environment | .venv (Windows) | Virtual environment |

**Hardware:**
- GPU: NVIDIA RTX A1000 6GB (unused for inference — all via API)
- CPU: Intel i9-13950HX
- RAM: 64GB
- OS: Windows

---

## ADR-016: Reference Document Selection

**Status:** Accepted  
**Date:** 2026-05-19  
**Context:**  
The system needs a mechanism to select which reference document drives the output format.

**Decision:**  
- Default reference: first `_raw.txt` file found in `data/parsed/` (sorted alphabetically)
- Can be overridden via `case_context["reference_text"]`
- Currently: `judgement_4_raw.txt` (Gujarat Revenue Department Secretary-level order, 5 pages)
- Reference documents are Gujarat Revenue Department administrative orders (not High Court judgements)

**Consequences:**  
- Output style determined by which reference is loaded
- To produce different styles, parse different reference PDFs
- No manual template authoring needed

---

## Decision Log

| # | Decision | Date | Status |
|---|----------|------|--------|
| 001 | System is Format Replicator, not RAG/QA | 2024-03-15 (rev. 2026-05-19) | Accepted |
| 002 | Google Gemini Vision for OCR | 2026-05-19 | Accepted (supersedes GLM-OCR) |
| 003 | Implicit layout via Vision model + regex for DOCX | 2026-05-19 | Accepted (supersedes rule-based spatial) |
| 004 | Raw text intermediate format (not JSON schema) | 2026-05-19 | Accepted (supersedes typed schema) |
| 005 | FAISS + Gemini embeddings (supplementary role) | 2026-05-19 | Accepted (revised from primary) |
| 006 | gemini-embedding-001 (3072-dim) | 2026-05-19 | Accepted (supersedes multilingual-e5-large) |
| 007 | Single-pass format replication | 2026-05-19 | Accepted (supersedes section-by-section) |
| 008 | Google Gemini API (cloud, free tier) | 2026-05-19 | Accepted (supersedes local Qwen2.5) |
| 009 | Context-aware DOCX with alignment detection | 2026-05-19 | Accepted (revised formatting logic) |
| 010 | Template learning deprecated | 2026-05-19 | Deprecated |
| 011 | Replicate-only pipeline mode | 2026-05-19 | Accepted (simplified from 3 modes) |
| 012 | API quota rotation for rate limits | 2026-05-19 | Accepted (revised from graceful degradation) |
| 013 | Cloud-dependent architecture | 2026-05-19 | Accepted (supersedes local-first) |
| 014 | Numbering via format replication (implicit) | 2026-05-19 | Accepted (revised from explicit schema) |
| 015 | Actual technology stack | 2026-05-19 | Accepted (revised) |
| 016 | Reference document selection mechanism | 2026-05-19 | Accepted (new) |
