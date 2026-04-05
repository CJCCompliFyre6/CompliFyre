import openai
import logging
import string
import fitz
import re
import json
from typing import Tuple, Optional, Dict, Any
from app.services.automate_task import (
    session_scope,
)
from app.models import RawLLMResponse
from flask_login import login_required, current_user
from flask import flash, request
from app import db

logger = logging.getLogger(__name__)

def check_free_report_used():
    """Utility function to check if free report was used"""
    if current_user.free_report_used:
        flash("This feature is disabled after report generation. Please contact CompliFyre@crackerjacktech.com for assistance.", "error")
        return True
    return False



def extract_context_text(file_path: str, start_page: int, end_page: int) -> str:
    """Extract text from PDF pages for context analysis"""
    try:
        with fitz.open(file_path) as doc:
            text_parts = []
            for page_num in range(start_page - 1, end_page):  # fitz uses 0-indexed
                page = doc[page_num]
                text_parts.append(page.get_text())
            return "\n".join(text_parts)
    except Exception as e:
        logger.error(f"Error extracting context text: {str(e)}")
        return ""



def extract_structured_info_with_metrics(query: str, vector_store_id: str, schema) -> Tuple[Optional[Any], Dict[str, int]]:
    """Enhanced version that returns both response and token metrics for OpenAI"""
    try:
        # Call OpenAI API
        response = openai.chat.completions.create(
            model="gpt-4o-mini",  # Using gpt-4o-mini as specified
            messages=[{"role": "user", "content": query}],
            response_format={"type": "json_object"},
            temperature=0
        )
        
        # Extract token usage from OpenAI response
        usage_metrics = {
            'prompt_tokens': response.usage.prompt_tokens,
            'completion_tokens': response.usage.completion_tokens,
            'total_tokens': response.usage.total_tokens,
        }
        
        # Parse response
        if response.choices[0].message.content:
            parsed_response = schema.model_validate_json(response.choices[0].message.content)
            return parsed_response, usage_metrics
        
        return None, usage_metrics
        
    except openai.APIError as e:
        logger.error(f"OpenAI API error: {str(e)}")
        return None, {}
    except Exception as e:
        logger.error(f"LLM extraction failed: {str(e)}")
        return None, {}

def analyze_extraction_quality(chunk_response, context_text: str, total_pages: int, page_range: str) -> dict:
    """Enhanced quality analysis with better missing clauses detection"""
    if not chunk_response or not hasattr(chunk_response, 'requirements'):
        return {
            'extracted_count': 0,
            'expected_count': estimate_expected_clauses(context_text, total_pages),
            'missing_clauses': ['all'],
            'confidence_score': 0.0,
            'quality_issues': ['no_response_or_empty_requirements']
        }
    
    requirements = chunk_response.requirements
    extracted_count = len(requirements) if requirements else 0
    
    # Calculate expected count
    expected_count = estimate_expected_clauses(context_text, total_pages)
    
    # Analyze quality issues
    quality_issues = []
    
    # Check for incomplete clauses
    incomplete_clauses = 0
    for clause in requirements:
        if not hasattr(clause, 'clause_text') or not clause.clause_text:
            incomplete_clauses += 1
        elif hasattr(clause, 'clause_text') and len(clause.clause_text.strip()) < 10:
            incomplete_clauses += 1
    
    if incomplete_clauses > 0:
        quality_issues.append(f'{incomplete_clauses}_incomplete_clauses')
    
    # Identify actual missing clauses
    missing_analysis = identify_actual_missing_clauses(context_text, requirements, page_range)
    
    # Calculate confidence with extraction rate
    extraction_rate = extracted_count / expected_count if expected_count > 0 else 0
    confidence_score = calculate_confidence_with_extraction_rate(extraction_rate, incomplete_clauses, extracted_count)
    
    return {
        'extracted_count': extracted_count,
        'expected_count': expected_count,
        'missing_clauses': missing_analysis,
        'confidence_score': confidence_score,
        'quality_issues': quality_issues,
        'incomplete_clauses_count': incomplete_clauses,
        'extraction_rate': extraction_rate
    }

def calculate_confidence_with_extraction_rate(extraction_rate: float, incomplete_count: int, total_extracted: int) -> float:
    """Calculate confidence based on extraction rate and quality"""
    if total_extracted == 0:
        return 0.0
    
    base_confidence = extraction_rate * 0.7  # 70% weight to extraction rate
    
    # Deduct for incomplete clauses
    completeness_penalty = (incomplete_count / total_extracted) * 0.3 if total_extracted > 0 else 0
    confidence = base_confidence - completeness_penalty
    
    return max(0.0, min(1.0, confidence))

def calculate_confidence_score(response, context_text: str) -> float:
    """Calculate confidence score based on various factors"""
    confidence = 0.5  # Base confidence
    
    if not response or not hasattr(response, 'requirements'):
        return 0.0
    
    requirements = response.requirements
    
    # Factor 1: Number of clauses extracted relative to context length
    if context_text and requirements:
        word_count = len(context_text.split())
        clause_count = len(requirements)
        expected_ratio = min(clause_count / (word_count / 500), 1.0)  # Normalize
        confidence += expected_ratio * 0.3
    
    # Factor 2: Completeness of clause information
    complete_clauses = 0
    for clause in requirements:
        if hasattr(clause, 'clause_text') and clause.clause_text:
            if hasattr(clause, 'clause_number') and clause.clause_number:
                complete_clauses += 1
    
    if requirements:
        completeness_ratio = complete_clauses / len(requirements)
        confidence += completeness_ratio * 0.2
    
    return min(confidence, 1.0)

def identify_potential_missing_clauses(context_text: str, extracted_clauses: list) -> list:
    """Identify potential missing clauses by analyzing text patterns"""
    if not context_text or not extracted_clauses:
        return []
    
    missing = []
    
    # Look for common clause patterns in text that weren't extracted
    clause_patterns = [
        r'clause\s+(\d+[\.\d]*)',
        r'section\s+(\d+[\.\d]*)', 
        r'article\s+(\d+[\.\d]*)',
        r'§\s*(\d+[\.\d]*)'
    ]
    
    extracted_numbers = []
    for clause in extracted_clauses:
        if hasattr(clause, 'clause_number') and clause.clause_number:
            extracted_numbers.append(str(clause.clause_number))
    
    for pattern in clause_patterns:
        matches = re.findall(pattern, context_text, re.IGNORECASE)
        for match in matches:
            if match not in extracted_numbers and match not in missing:
                missing.append(match)
    
    return missing[:10]  # Return top 10 potential missing clauses

def analyze_overall_missing_data(guideline_id: int, all_extracted_numbers: list):
    """Analyze missing data across all extraction chunks"""
    try:
        with session_scope() as session:
            # Update all raw responses with overall missing data analysis
            raw_responses = session.query(RawLLMResponse).filter_by(
                guideline_id=guideline_id
            ).all()
            
            for response in raw_responses:
                if response.missing_clauses:
                    current_missing = json.loads(response.missing_clauses)
                    # Add cross-chunk missing analysis
                    enhanced_missing = {
                        'chunk_specific': current_missing,
                        'overall_extracted_count': len(all_extracted_numbers),
                        'unique_clauses_extracted': list(set(all_extracted_numbers))
                    }
                    response.missing_clauses = json.dumps(enhanced_missing)
            
            session.commit()
    except Exception as e:
        logger.error(f"Error in overall missing data analysis: {str(e)}")



def clean_string_for_db(text: str) -> str:
    """
    Clean string by removing null characters and other problematic characters for database storage.
    """
    if not text:
        return text
    
    # Remove null characters (0x00)
    text = text.replace('\x00', '')
    
    # Remove other control characters that might cause issues
    # Keep only printable characters and common whitespace
    printable = set(string.printable)
    text = ''.join(filter(lambda x: x in printable, text))
    
    # Remove any remaining problematic characters
    text = text.encode('utf-8', 'ignore').decode('utf-8')
    
    return text


def safe_model_dump_json(model_obj) -> str:
    """
    Safely convert model to JSON, handling any serialization issues.
    """
    try:
        json_str = model_obj.model_dump_json()
        # Clean the JSON string
        return clean_string_for_db(json_str)
    except Exception as e:
        logger.error(f"Error in safe_model_dump_json: {str(e)}")
        # Return a safe representation
        try:
            return json.dumps({"error": "Could not serialize response", "type": str(type(model_obj))})
        except:
            return "Serialization error"

def estimate_expected_clauses(context_text: str, total_pages: int) -> int:
    """
    Estimate how many clauses we should expect based on document characteristics.
    """
    if not context_text:
        return 0
    
    # Method 1: Based on word count (rough estimate)
    word_count = len(context_text.split())
    estimated_by_words = max(5, word_count // 200)  # Roughly 1 clause per 200 words
    
    # Method 2: Based on page count
    estimated_by_pages = max(3, total_pages * 2)  # Roughly 2 clauses per page
    
    # Method 3: Based on section headings and numbering patterns
    section_patterns = [
        r'\b\d+\.\d+\b',  # Pattern like 1.1, 2.3, etc.
        r'\b\d+\.\s+[A-Z]',  # Pattern like "1. CAPITAL"
        r'\bArticle\s+\d+',  # Pattern like "Article 1"
        r'\bSection\s+\d+',  # Pattern like "Section 1"
    ]
    
    unique_clause_numbers = set()
    for pattern in section_patterns:
        matches = re.findall(pattern, context_text)
        unique_clause_numbers.update(matches)
    
    estimated_by_patterns = len(unique_clause_numbers)
    
    # Take the maximum of all methods
    expected_count = max(estimated_by_words, estimated_by_pages, estimated_by_patterns)
    
    return expected_count


def identify_actual_missing_clauses(context_text: str, extracted_clauses: list, page_range: str) -> dict:
    """
    Identify actual missing clauses by analyzing document structure and patterns.
    """
    if not context_text:
        return {"missing_clauses": [], "analysis_method": "no_context"}
    
    extracted_numbers = set()
    extracted_text_snippets = set()
    
    # Collect extracted data
    for clause in extracted_clauses:
        if hasattr(clause, 'clause_number') and clause.clause_number:
            extracted_numbers.add(clause.clause_number.strip())
        if hasattr(clause, 'clause_text') and clause.clause_text:
            snippet = clause.clause_text[:100].lower().strip()
            extracted_text_snippets.add(snippet)
    
    # Method 1: Find numbered clauses in text that weren't extracted
    numbered_patterns = [
        r'(\d+\.\d+)\s',  # Pattern: 1.1, 2.3, etc.
        r'\((\d+\.\d+)\)',  # Pattern: (1.1), (2.3)
        r'Clause\s+(\d+\.\d+)',  # Pattern: Clause 1.1
        r'Section\s+(\d+\.\d+)',  # Pattern: Section 1.1
        r'Article\s+(\d+\.\d+)',  # Pattern: Article 1.1
    ]
    
    potential_missing = set()
    for pattern in numbered_patterns:
        matches = re.findall(pattern, context_text)
        for match in matches:
            if match not in extracted_numbers:
                potential_missing.add(match)
    
    # Method 2: Look for clause-like headings that weren't extracted
    heading_patterns = [
        r'\n(\d+\.\d+\s+[A-Z][A-Za-z\s]{10,50})\.?\n',  # Numbered headings
        r'\n([A-Z][A-Za-z\s]{15,60}):?\n',  # Capitalized headings
        r'\n(\d+\.\s+[A-Z][A-Za-z\s]{10,50})\.?\n',  # Single number headings
    ]
    
    for pattern in heading_patterns:
        matches = re.findall(pattern, context_text)
        for match in matches:
            # Check if this heading appears in extracted clauses
            match_lower = match.lower()
            found_in_extracted = any(match_lower in snippet for snippet in extracted_text_snippets)
            if not found_in_extracted:
                potential_missing.add(f"heading: {match.strip()}")
    
    # Method 3: Analyze sequential numbering gaps
    sequential_missing = find_sequential_gaps(extracted_numbers)
    
    return {
        "missing_clauses": list(potential_missing)[:10],  # Limit to top 10
        "sequential_gaps": sequential_missing,
        "extracted_count": len(extracted_clauses),
        "analysis_method": "multi_method",
        "page_range": page_range
    }

def find_sequential_gaps(extracted_numbers: set) -> list:
    """
    Find gaps in sequential numbering (e.g., if we have 1.1, 1.3, then 1.2 is missing)
    """
    gaps = []
    
    # Convert to list and sort
    numbers = list(extracted_numbers)
    
    # Try to parse as decimal numbers
    decimal_numbers = []
    for num in numbers:
        try:
            # Handle both "1.1" and "1" formats
            if '.' in num:
                decimal_numbers.append(float(num))
            else:
                decimal_numbers.append(float(num))
        except ValueError:
            continue
    
    if not decimal_numbers:
        return gaps
    
    decimal_numbers.sort()
    
    # Find gaps in the sequence
    for i in range(1, len(decimal_numbers)):
        prev = decimal_numbers[i-1]
        curr = decimal_numbers[i]
        
        # If there's a gap greater than 0.1 but less than 1.0, it might be missing
        if 0.1 < (curr - prev) < 1.0:
            missing_num = prev + 0.1
            # Format back to string (handle both 1.0 and 1 formats)
            if missing_num == int(missing_num):
                gaps.append(str(int(missing_num)))
            else:
                gaps.append(f"{missing_num:.1f}")
    
    return gaps