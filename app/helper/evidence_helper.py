"""
Helper functions for evidence processing and validation
"""

import os
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def format_invalid_evidence_html(
    answer: str, reason: str, confidence: float = 0.0
) -> str:
    """
    Formats invalid evidence with proper HTML styling.

    Args:
        answer: The AI's analysis of the evidence
        reason: Why the evidence is invalid
        confidence: Confidence score (0-1)

    Returns:
        HTML formatted string
    """
    return f"""
    <div style='background: linear-gradient(to right, #fee2e2, #fef2f2); 
                padding: 16px; 
                border-radius: 8px; 
                border-left: 4px solid #dc2626; 
                margin: 8px 0;'>
        <div style='display: flex; align-items: center; margin-bottom: 12px;'>
            <svg style='width: 24px; height: 24px; color: #dc2626; margin-right: 8px;' 
                 fill='none' stroke='currentColor' viewBox='0 0 24 24'>
                <path stroke-linecap='round' stroke-linejoin='round' stroke-width='2' 
                      d='M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z'/>
            </svg>
            <strong style='color: #991b1b; font-size: 16px;'>Invalid Evidence</strong>
            {f"<span style='margin-left: auto; background: #dc2626; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px;'>Confidence: {confidence:.0%}</span>" if confidence > 0 else ""}
        </div>
        
        <div style='background: white; padding: 12px; border-radius: 4px; margin-bottom: 12px;'>
            <p style='color: #374151; margin: 0; line-height: 1.6;'>{answer}</p>
        </div>
        
        <div style='background: #fef2f2; padding: 12px; border-radius: 4px; border: 1px solid #fecaca;'>
            <p style='margin: 0 0 4px 0; font-weight: 600; color: #991b1b; font-size: 14px;'>
                ⚠️ Reason for Rejection:
            </p>
            <p style='color: #7f1d1d; margin: 0; line-height: 1.5;'>{reason}</p>
        </div>
        
        <div style='margin-top: 12px; padding: 8px; background: #fffbeb; border-radius: 4px; border-left: 3px solid #f59e0b;'>
            <p style='margin: 0; font-size: 13px; color: #92400e;'>
                💡 <strong>What to do:</strong> Please upload a document that specifically addresses 
                the requirement or provide manual evidence.
            </p>
        </div>
    </div>
    """


def format_valid_evidence_html(answer: str, confidence: float = 0.0) -> str:
    """
    Formats valid evidence with confidence indicator.

    Args:
        answer: The extracted evidence
        confidence: Confidence score (0-1)

    Returns:
        HTML formatted string (or just the answer if high confidence)
    """
    if confidence >= 0.8:
        # High confidence - return clean answer
        return answer
    elif confidence >= 0.5:
        # Medium confidence - add subtle warning
        return f"""
        <div style='background: #fffbeb; padding: 12px; border-radius: 6px; border-left: 3px solid #f59e0b; margin-bottom: 8px;'>
            <p style='margin: 0; font-size: 13px; color: #92400e;'>
                ⚠️ <strong>Medium Confidence ({confidence:.0%})</strong> - Please review this evidence carefully.
            </p>
        </div>
        {answer}
        """
    else:
        # Low confidence - add warning
        return f"""
        <div style='background: #fef2f2; padding: 12px; border-radius: 6px; border-left: 3px solid #ef4444; margin-bottom: 8px;'>
            <p style='margin: 0; font-size: 13px; color: #991b1b;'>
                ⚠️ <strong>Low Confidence ({confidence:.0%})</strong> - This evidence may not fully meet the requirement.
            </p>
        </div>
        {answer}
        """


def format_processing_error_html(error_message: str) -> str:
    """
    Formats processing error with helpful information.

    Args:
        error_message: The error message

    Returns:
        HTML formatted string
    """
    return f"""
    <div style='background: #fef2f2; padding: 16px; border-radius: 8px; border-left: 4px solid #dc2626;'>
        <div style='display: flex; align-items: center; margin-bottom: 12px;'>
            <svg style='width: 24px; height: 24px; color: #dc2626; margin-right: 8px;' 
                 fill='none' stroke='currentColor' viewBox='0 0 24 24'>
                <path stroke-linecap='round' stroke-linejoin='round' stroke-width='2' 
                      d='M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z'/>
            </svg>
            <strong style='color: #991b1b;'>Processing Failed</strong>
        </div>
        
        <p style='color: #7f1d1d; margin: 0 0 12px 0;'>{error_message}</p>
        
        <div style='background: #fffbeb; padding: 12px; border-radius: 4px; border-left: 3px solid #f59e0b;'>
            <p style='margin: 0 0 8px 0; font-weight: 600; color: #92400e;'>💡 Troubleshooting Tips:</p>
            <ul style='margin: 0; padding-left: 20px; color: #92400e;'>
                <li>Ensure the file is not corrupted or password-protected</li>
                <li>Try converting the file to PDF format</li>
                <li>Check that the file contains readable text (not just images)</li>
                <li>For large files, consider splitting into smaller sections</li>
                <li>If the issue persists, provide evidence manually</li>
            </ul>
        </div>
    </div>
    """


def validate_file_for_processing(file_path: str) -> Dict[str, Any]:
    """
    Validates a file before processing.

    Args:
        file_path: Path to the file

    Returns:
        Dict with 'valid', 'message', 'file_size_mb', 'warnings'
    """
    result = {"valid": True, "message": "", "file_size_mb": 0.0, "warnings": []}

    try:
        # Check file exists
        if not os.path.exists(file_path):
            result["valid"] = False
            result["message"] = "File not found"
            return result

        # Check file size
        file_size = os.path.getsize(file_path) / (1024 * 1024)
        result["file_size_mb"] = file_size

        if file_size > 50:
            result["warnings"].append(
                f"Very large file ({file_size:.1f} MB) - processing may be slow"
            )
        elif file_size > 20:
            result["warnings"].append(
                f"Large file ({file_size:.1f} MB) - this may take a few minutes"
            )

        # Check file extension
        _, ext = os.path.splitext(file_path)
        ext = ext.lower()

        if ext in [".exe", ".dll", ".so", ".dylib"]:
            result["valid"] = False
            result["message"] = "Executable files are not allowed"
            return result

        # Warn about potentially problematic formats
        if ext in [".zip", ".rar", ".7z"]:
            result["warnings"].append(
                "Compressed files may not process correctly - consider extracting first"
            )

        if ext in [".jpg", ".jpeg", ".png", ".gif"]:
            result["warnings"].append(
                "Image files require OCR - text extraction may be limited"
            )

        result["message"] = "File is valid for processing"
        return result

    except Exception as e:
        result["valid"] = False
        result["message"] = f"Error validating file: {str(e)}"
        return result


def get_user_friendly_error_message(error: Exception) -> str:
    """
    Converts technical errors into user-friendly messages.

    Args:
        error: The exception

    Returns:
        User-friendly error message
    """
    error_str = str(error).lower()

    if "timeout" in error_str:
        return "The file took too long to process. Please try a smaller file or contact support."

    if "memory" in error_str or "out of memory" in error_str:
        return "The file is too large to process. Please try splitting it into smaller parts."

    if "corrupt" in error_str or "invalid" in error_str:
        return "The file appears to be corrupted or in an invalid format. Please try re-saving or converting it."

    if "permission" in error_str or "access" in error_str:
        return "Unable to access the file. Please check file permissions and try again."

    if "api" in error_str or "rate limit" in error_str:
        return "Service temporarily unavailable. Please try again in a few moments."

    # Generic fallback
    return "An unexpected error occurred while processing the file. Please try again or contact support."


def log_evidence_processing(
    evidence_id: str,
    file_name: str,
    file_size_mb: float,
    is_relevant: bool,
    confidence: float,
    processing_time: float,
):
    """
    Logs evidence processing for analytics and debugging.

    Args:
        evidence_id: Evidence ID
        file_name: Name of processed file
        file_size_mb: File size in MB
        is_relevant: Whether evidence was relevant
        confidence: Confidence score
        processing_time: Time taken in seconds
    """
    logger.info(
        f"Evidence Processing Complete | "
        f"ID: {evidence_id} | "
        f"File: {file_name} | "
        f"Size: {file_size_mb:.2f}MB | "
        f"Relevant: {is_relevant} | "
        f"Confidence: {confidence:.2%} | "
        f"Time: {processing_time:.2f}s"
    )

    # Log warnings for problematic cases
    if not is_relevant:
        logger.warning(f"Irrelevant evidence detected for ID {evidence_id}")

    if confidence < 0.5:
        logger.warning(
            f"Low confidence ({confidence:.2%}) for evidence ID {evidence_id}"
        )

    if file_size_mb > 20:
        logger.info(
            f"Large file processed ({file_size_mb:.2f}MB) for evidence ID {evidence_id}"
        )
