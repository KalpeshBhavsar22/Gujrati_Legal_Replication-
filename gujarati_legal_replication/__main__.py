"""
CLI entry point for the Gujarati Legal Judgement Replication System.

Usage:
    # Index reference judgements
    python -m gujarati_legal_replication index --pdf-dir ./data/input_pdfs
    
    # Generate new judgement
    python -m gujarati_legal_replication generate --case-file case_context.json
    
    # Replicate structure from a specific judgement
    python -m gujarati_legal_replication replicate --source judgement.pdf --case-file case.json
"""

import argparse
import json
import logging
from pathlib import Path

from .config import PipelineConfig
from .pipeline import JudgementReplicationPipeline


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_index(args, pipeline):
    """Index reference judgements."""
    pdf_dir = Path(args.pdf_dir) if args.pdf_dir else None
    pipeline.index_reference_corpus(pdf_dir)


def cmd_generate(args, pipeline):
    """Generate a new judgement."""
    case_context = json.loads(Path(args.case_file).read_text(encoding="utf-8"))
    
    output_path = pipeline.generate_judgement(
        case_context=case_context,
        document_type=args.doc_type,
        output_format=args.format,
    )
    print(f"Generated: {output_path}")


def cmd_replicate(args, pipeline):
    """Replicate structure from source judgement."""
    case_context = json.loads(Path(args.case_file).read_text(encoding="utf-8"))
    
    output_path = pipeline.replicate_structure(
        source_pdf=Path(args.source),
        new_case_context=case_context,
        output_format=args.format,
    )
    print(f"Replicated: {output_path}")


def cmd_parse(args, pipeline):
    """Parse a single PDF to structured JSON (debugging/inspection)."""
    pdf_path = Path(args.pdf)
    schema = pipeline.process_single_pdf(pdf_path)
    
    print(f"\nParsed: {pdf_path.name}")
    print(f"  Sections: {len(schema.sections)}")
    print(f"  Parties: {len(schema.parties)}")
    for section in schema.sections:
        print(f"    [{section.section_type}] {section.title} "
              f"({len(section.subsections)} subsections)")


def main():
    parser = argparse.ArgumentParser(
        description="Gujarati Legal Judgement Replication System"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Index command
    idx_parser = subparsers.add_parser("index", help="Index reference judgements")
    idx_parser.add_argument("--pdf-dir", help="Directory containing reference PDFs")
    
    # Generate command
    gen_parser = subparsers.add_parser("generate", help="Generate new judgement")
    gen_parser.add_argument("--case-file", required=True, help="JSON file with case context")
    gen_parser.add_argument("--doc-type", default="general", help="Document type template")
    gen_parser.add_argument("--format", default="docx", choices=["docx", "text", "json"])
    
    # Replicate command
    rep_parser = subparsers.add_parser("replicate", help="Replicate structure from source")
    rep_parser.add_argument("--source", required=True, help="Source PDF to replicate")
    rep_parser.add_argument("--case-file", required=True, help="JSON file with new case context")
    rep_parser.add_argument("--format", default="docx", choices=["docx", "text", "json"])
    
    # Parse command (for debugging)
    parse_parser = subparsers.add_parser("parse", help="Parse single PDF to JSON")
    parse_parser.add_argument("--pdf", required=True, help="PDF file to parse")
    
    args = parser.parse_args()
    setup_logging(args.verbose)
    
    if not args.command:
        parser.print_help()
        return
    
    # Initialize pipeline
    config = PipelineConfig()
    pipeline = JudgementReplicationPipeline(config)
    
    # Dispatch command
    commands = {
        "index": cmd_index,
        "generate": cmd_generate,
        "replicate": cmd_replicate,
        "parse": cmd_parse,
    }
    commands[args.command](args, pipeline)


if __name__ == "__main__":
    main()
