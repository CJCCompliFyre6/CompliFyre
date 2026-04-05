import os
import hashlib
import PyPDF2
from typing import List, Dict


def estimate_document_pages(file_path: str) -> int:
    """
    Estimate the number of pages in a document.
    """
    if not os.path.exists(file_path):
        return 0

    try:
        if file_path.lower().endswith(".pdf"):
            with open(file_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)
                return len(pdf_reader.pages)

        elif file_path.lower().endswith((".docx", ".doc")):
            # Rough estimate for Word docs: 500 words ≈ 1 page
            with open(file_path, "rb") as file:
                content = file.read()
                word_count = len(content) / 5  # Very rough estimate
                return max(1, int(word_count / 500))

        else:
            # For text files, estimate 500 words per page
            with open(file_path, "r", encoding="utf-8", errors="ignore") as file:
                text = file.read()
                word_count = len(text.split())
                return max(1, int(word_count / 500))

    except Exception as e:
        print(f"Error estimating pages: {e}")
        return 0


def create_chunk_summary_prompt(
    all_chunks_results: List[Dict], item_description: str
) -> str:
    """
    Create a prompt to summarize findings from all chunks.
    """
    chunk_summaries = []

    for i, result in enumerate(all_chunks_results):
        if result.get("evidence_found", False):
            summary = f"Chunk {i+1}: {result.get('relevant_text', '')[:200]}..."
            chunk_summaries.append(summary)

    prompt = f"""
    Summarize the following evidence findings for: "{item_description}"
    
    Chunk Summaries:
    {chr(10).join(chunk_summaries) if chunk_summaries else 'No evidence found in any chunk.'}
    
    Provide a comprehensive summary that:
    1. Identifies all relevant evidence
    2. Notes any patterns or inconsistencies
    3. Highlights the strongest evidence
    4. Mentions any gaps or missing information
    5. Provides an overall assessment
    
    Format as a clear, concise audit finding.
    """

    return prompt



