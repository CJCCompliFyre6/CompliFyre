from app import client
import os
import concurrent.futures
from tqdm import tqdm
import uuid
import time
from typing import Any, Type,TypeVar, Union
from pydantic import BaseModel, ValidationError
from openai import OpenAI, APIError
from celery.utils.log import get_task_logger
import pandas as pd
import base64
import mimetypes
import json
import re
import time
import logging


logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)




def create_vector_store(store_name: str) -> dict:
    try:
        vector_store = client.vector_stores.create(
            name=f"{store_name}_{str(uuid.uuid4())[:8]}"
        )

        # Debug: Print the type and available attributes
        logger.info(f"Vector store type: {type(vector_store)}")
        logger.info(f"Vector store attributes: {dir(vector_store)}")
        logger.info(f"Vector store content: {vector_store}")

        # Try different ways to access the data
        if hasattr(vector_store, "id"):
            logger.info("Has 'id' attribute")
            vector_id = vector_store.id
        elif hasattr(vector_store, "get"):
            logger.info("Has 'get' method - treating as dict-like")
            vector_id = vector_store.get("id")
        else:
            logger.info("Converting to dict")
            vector_dict = (
                dict(vector_store)
                if hasattr(vector_store, "__iter__")
                else str(vector_store)
            )
            logger.info(f"Dict conversion: {vector_dict}")
            return {}

        details = {
            "id": vector_id,
            "name": getattr(vector_store, "name", "unknown"),
            "created_at": getattr(vector_store, "created_at", "unknown"),
            "file_count": getattr(
                getattr(vector_store, "file_counts", {}), "completed", 0
            ),
        }

        logger.info(f"Vector store created: {details}")
        return details

    except Exception as e:
        logger.warning(f"Error creating vector store: {e}")
        logger.warning(f"Error type: {type(e)}")
        import traceback

        logger.warning(f"Traceback: {traceback.format_exc()}")
        return {}


# --- Step 2: Upload single file ---
def upload_single_file(file_path: str, vector_store_id: str):
    try:
        # Open the file in binary mode
        with open(file_path, "rb") as f:
            # Upload file to OpenAI
            file_response = client.files.create(file=f, purpose="assistants")
            print(file_response)

        # Attach file to vector store
        client.vector_stores.files.create(
            vector_store_id=vector_store_id, file_id=file_response.id
        )

        print(
            f"Uploaded {os.path.basename(file_path)} to vector store {vector_store_id}"
        )
        return {"status": "success", "file_id": file_response.id}
    except Exception as e:
        print(f"Error with {file_path}: {str(e)}")
        return {"status": "failed", "error": str(e)}


def delete_vector_store(vector_store_id: str) -> dict:
    """
    Deletes the specified vector store.

    Args:
        vector_store_id: The ID of the vector store to delete.

    Returns:
        A dictionary with the status of the deletion.
    """
    if not client:
        return {"status": "failed", "error": "OpenAI client not initialized."}
    try:
        logger.info(f"Attempting to delete vector store with ID: {vector_store_id}")
        response = client.vector_stores.delete(vector_store_id=vector_store_id)

        logger.info(f"Successfully deleted vector store. Response: {response}")
        return {"status": "success", "id": response.id, "deleted": response.deleted}
    except Exception as e:
        logger.error(
            f"Error deleting vector store {vector_store_id}: {e}", exc_info=True
        )
        return {"status": "failed", "error": str(e)}


def delete_file(file_id: str) -> dict:
    """
    Deletes the specified file from OpenAI.

    Args:
        file_id: The ID of the file to delete.

    Returns:
        A dictionary with the status of the deletion.
    """
    if not client:
        return {"status": "failed", "error": "OpenAI client not initialized."}
    try:
        logger.info(f"Attempting to delete file with ID: {file_id}")
        response = client.files.delete(file_id=file_id)

        logger.info(f"Successfully deleted file. Response: {response}")
        return {"status": "success", "id": response.id, "deleted": response.deleted}
    except Exception as e:
        logger.error(f"Error deleting file {file_id}: {e}", exc_info=True)
        return {"status": "failed", "error": str(e)}


# # --- Step 3: Extract structured info ---
# # Updated `extract_structured_info` function with retry and fallback logic


def extract_structured_info(
    query: str,
    vector_store_id: str,
    schema: Any,
    retries: int = 2,
    backoff_factor: float = 1.5,
) -> Any | None:
    """
    Extracts structured info from the model with retry and fallback logic.
    Enhanced with regex fallback for compliance activities.
    """
    attempt = 0

    # FIX: Handle None vector_store_id
    tools = []
    if vector_store_id:
        tools = [
            {
                "type": "file_search",
                "vector_store_ids": [vector_store_id],
            }
        ]

    while attempt < retries:
        try:
            logger.info(
                "Attempt #%d to extract structured info for schema: %s",
                attempt + 1,
                schema.__name__,
            )

            # FIX: Only include tools if vector_store_id is provided
            if tools:
                response = client.responses.parse(
                    input=query, model="gpt-4o-mini", tools=tools, text_format=schema
                )
            else:
                # FIX: Call without tools when no vector_store_id
                response = client.responses.parse(
                    input=query, model="gpt-4o-mini", text_format=schema
                )

            # Check for a successful parse and valid output
            if response and response.output_parsed is not None:
                logger.info("Successfully extracted structured data.")
                return response.output_parsed

            # If the model returns None, raise an error to trigger a retry
            raise ValueError("Model returned None or an empty response.")

        except (ValidationError, ValueError) as e:
            logger.warning(
                "Attempt #%d failed with a data validation error: %s", attempt + 1, e
            )

            # NEW: On the last attempt, try regex fallback for compliance activities
            if attempt == retries - 1 and schema.__name__ == "ComplianceRequirements":
                logger.info("Trying regex fallback for compliance activities...")
                return _extract_compliance_with_regex_fallback(query, tools)

        except Exception as e:
            logger.warning(
                "Attempt #%d failed with a general error: %s", attempt + 1, e
            )

        attempt += 1
        if attempt < retries:
            wait_time = backoff_factor**attempt
            logger.info("Waiting %.2f seconds before retrying...", wait_time)
            time.sleep(wait_time)

    logger.error(
        "All %d attempts failed to extract structured data. Returning a default empty object.",
        retries,
    )

    # FIX: Return None instead of empty schema to indicate failure
    return None


def _extract_compliance_with_regex_fallback(query: str, tools: list) -> Any | None:
    """
    Fallback method using regex extraction with proper data transformation
    """
    try:
        import re
        import json

        # Use the same approach as your working PDFService.retrive_regulatory_complience method
        if tools:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful AI that extracts structured information from regulatory documents.",
                    },
                    {"role": "user", "content": query},
                ],
            )
        else:
            # If no vector store, use basic completion
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful AI that extracts structured information from regulatory documents.",
                    },
                    {"role": "user", "content": query},
                ],
            )

        result = response.choices[0].message.content
        logger.info(
            "Regex fallback - Raw AI response: %s", result[:500] if result else "Empty"
        )

        # Extract JSON using regex (same as your working method)
        pattern = r"```json(.*?)```"
        matches = re.findall(pattern, result, re.DOTALL)

        if matches:
            json_str = matches[0].strip()
            logger.info("Regex fallback - Extracted JSON: %s", json_str[:500])

            # Parse and transform the JSON to match schema
            data = json.loads(json_str)

            # TRANSFORM DATA to match schema
            transformed_data = _transform_compliance_data(data, query)

            if transformed_data and "compliance_activities" in transformed_data:
                # Create ComplianceRequirements object
                from app.services.prompt_templates.compliance_activity import (
                    ComplianceRequirements,
                )

                return ComplianceRequirements(**transformed_data)

        logger.warning("Regex fallback also failed to extract valid JSON")
        return None

    except Exception as e:
        logger.error("Regex fallback failed: %s", str(e))
        return None


def _transform_compliance_data(raw_data: dict, query: str) -> dict:
    """
    Transform AI response to match ComplianceRequirements schema
    """
    try:
        # Extract clause text from query for fallback
        clause_text = _extract_clause_from_query(query)

        # Handle different response formats
        activities = []

        # Case 1: Direct compliance_activities
        if "compliance_activities" in raw_data:
            activities = raw_data["compliance_activities"]
        # Case 2: Nested under ComplianceRequirements
        elif "ComplianceRequirements" in raw_data:
            activities = raw_data["ComplianceRequirements"]
        # Case 3: Direct array
        elif isinstance(raw_data, list):
            activities = raw_data
        else:
            # Try to find activities in any key
            for key, value in raw_data.items():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    activities = value
                    break

        if not activities:
            return None

        transformed_activities = []

        for i, activity in enumerate(activities, 1):
            # Ensure all required fields with proper types
            transformed_activity = {}

            # Handle relevant_departments - convert list to string if needed
            relevant_depts = activity.get("relevant_departments", "Unknown")
            if isinstance(relevant_depts, list):
                transformed_activity["relevant_departments"] = ", ".join(relevant_depts)
            else:
                transformed_activity["relevant_departments"] = str(relevant_depts)

            # Handle activity_id - ensure it's string
            activity_id = activity.get("activity_id", i)
            if isinstance(activity_id, int):
                transformed_activity["activity_id"] = str(activity_id)
            else:
                transformed_activity["activity_id"] = str(activity_id)

            # Handle clause - use from query if missing
            clause = activity.get("clause", clause_text)
            transformed_activity["clause"] = clause

            # Copy other fields with type safety
            transformed_activity["compliance_level"] = str(
                activity.get("compliance_level", "Design")
            )
            transformed_activity["department_id"] = int(
                activity.get("department_id", 0)
            )
            transformed_activity["process_name"] = str(
                activity.get("process_name", "Unknown")
            )
            transformed_activity["sub_process_name"] = str(
                activity.get("sub_process_name", "Unknown")
            )
            transformed_activity["activity_description"] = str(
                activity.get("activity_description", "")
            )
            transformed_activity["responsible_party"] = str(
                activity.get("responsible_party", "Unknown")
            )
            transformed_activity["frequency"] = str(
                activity.get("frequency", "As needed")
            )
            transformed_activity["evidence_required"] = str(
                activity.get("evidence_required", "")
            )
            transformed_activity["justification"] = str(
                activity.get("justification", "")
            )

            transformed_activities.append(transformed_activity)

        return {"compliance_activities": transformed_activities}

    except Exception as e:
        logger.error("Data transformation failed: %s", str(e))
        return None


def _extract_clause_from_query(query: str) -> str:
    """
    Extract clause text from the query for fallback
    """
    try:
        # Look for "Regulatory Clause:" in the query
        import re

        match = re.search(r"Regulatory Clause:\s*(.*?)(?:\n|$)", query)
        if match:
            return match.group(1).strip()
        return "Clause text not available"
    except:
        return "Clause text not available"


def extract_structured_info_2(
    query: str, schema: Any, retries: int = 2, backoff_factor: float = 1.5
) -> Any | None:
    """
    Extracts structured info from the model with retry and fallback logic.

    Args:
        query: The prompt for the model.
        vector_store_id: The ID of the vector store to search.
        schema: The Pydantic model or schema to enforce structured output.
        retries: The number of times to retry the request on failure.
        backoff_factor: The multiplier for exponential backoff between retries.

    Returns:
        The parsed Pydantic object, or an empty Pydantic object if all retries fail.
    """
    attempt = 0
    while attempt < retries:
        try:
            logger.info(
                "Attempt #%d to extract structured info for schema: %s",
                attempt + 1,
                schema.__name__,
            )

            # This is the original call that might fail
            response = client.responses.parse(
                input=query, model="gpt-4o-mini", text_format=schema
            )

            # Check for a successful parse and valid output
            if response and response.output_parsed is not None:
                logger.info("Successfully extracted structured data.")
                return response.output_parsed

            # If the model returns None, raise an error to trigger a retry
            raise ValueError("Model returned None or an empty response.")

        except (ValidationError, ValueError) as e:
            # Catching ValidationError from pydantic and our custom ValueError
            logger.warning(
                "Attempt #%d failed with a data validation error: %s", attempt + 1, e
            )
        except Exception as e:
            # Catching generic errors like network issues or API errors
            logger.warning(
                "Attempt #%d failed with a general error: %s", attempt + 1, e
            )

        attempt += 1
        if attempt < retries:
            wait_time = backoff_factor**attempt
            logger.info("Waiting %.2f seconds before retrying...", wait_time)
            time.sleep(wait_time)

    logger.error(
        "All %d attempts failed to extract structured data. Returning a default empty object.",
        retries,
    )

    # Fallback to an empty instance of the schema
    if issubclass(schema, BaseModel):
        try:
            # Return a default, empty pydantic model instance
            return schema.model_construct()
        except Exception as e:
            logger.error(
                "Could not construct an empty schema instance for fallback: %s", e
            )
            return None

    # Final fallback if schema is not a BaseModel
    return {}


# ===========dynamic handeling of files=========================


def encode_image_to_base64(image_path: str) -> str:
    """Encodes an image file to a base64 data URI."""
    try:
        # Check if file exists
        if not os.path.exists(image_path):
            logger.error(f"Image file not found: {image_path}")
            raise FileNotFoundError(f"Image file not found: {image_path}")

        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type or not mime_type.startswith("image"):
            logger.error(f"Invalid or unknown image file type for {image_path}")
            raise ValueError(f"Invalid image file type: {mime_type}")

        with open(image_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
            result = f"{encoded_string}"
            logger.info(
                f"Successfully encoded image {image_path}, size: {len(result)} chars"
            )
            return result
    except Exception as e:
        logger.error(f"Failed to encode image {image_path}: {e}")
        raise  # Re-raise instead of returning empty string


def _get_config(file_name: str | None) -> dict:
    """
    Returns a config dict with model and processing options
    depending on the file extension.
    """

    config = {
        "model": "gpt-4o-mini",
        "preprocess": "text",
    }

    if not file_name:
        return config

    _, extension = os.path.splitext(file_name)
    extension = extension.lower()

    CONFIG_BY_EXTENSION = {
        # Documents → file_search supported
        ".pdf": {"model": "gpt-4o-mini",  "preprocess": "pdf"},
        ".doc": {"model": "gpt-4o-mini",  "preprocess": "docx"},
        ".docx": {
            "model": "gpt-4o-mini",
            "preprocess": "docx",
        },
        ".ppt": {"model": "gpt-4o-mini",  "preprocess": "ppt"},
        ".pptx": {"model": "gpt-4o-mini", "preprocess": "ppt"},
        # Spreadsheets → file_search not supported
        ".xls": {
            "model": "gpt-4o-mini",
            "preprocess": "excel",
        },
        ".xlsx": {
            "model": "gpt-4o-mini",
            "preprocess": "excel",
        },
        ".csv": {"model": "gpt-4o-mini",  "preprocess": "csv"},
        # Images → Vision
        ".png": {
            "model": "gpt-4o-mini",
            "preprocess": "image",
        },
        ".jpg": {
            "model": "gpt-4o-mini",
            "preprocess": "image",
        },
        ".jpeg": {
            "model": "gpt-4o-mini",
            "preprocess": "image",
        },
        ".gif": {
            "model": "gpt-4o-mini",
            "preprocess": "image",
        },
        ".bmp": {
            "model": "gpt-4o-mini",
            "preprocess": "image",
        },
        ".webp": {
            "model": "gpt-4o-mini",
            "preprocess": "image",
        },
        # Audio
        ".mp3": {
            "model": "gpt-4o-mini",
            "preprocess": "audio",
        },
        ".wav": {
            "model": "gpt-4o-mini",
            "preprocess": "audio",
        },
        ".m4a": {
            "model": "gpt-4o-mini",
            "preprocess": "audio",
        },
        ".flac": {
            "model": "gpt-4o-mini",
            "preprocess": "audio",
        },
        ".ogg": {
            "model": "gpt-4o-mini",
            "preprocess": "audio",
        },
        ".aac": {
            "model": "gpt-4o-mini",
            "preprocess": "audio",
        },
    }

    return CONFIG_BY_EXTENSION.get(extension, config)


def _preprocess_file(file_name: str, preprocess_type: str) -> str:
    """
    Converts Excel/CSV/Audio files into a text string for the model.
    """
    try:
        if preprocess_type == "excel":
            df = pd.read_excel(file_name)
            return df.to_csv(index=False)

        if preprocess_type == "csv":
            df = pd.read_csv(file_name)
            return df.to_csv(index=False)

        if preprocess_type == "audio":
            if not os.path.exists(file_name):
                raise FileNotFoundError(f"Audio file not found: {file_name}")

            with open(file_name, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1", file=audio_file
                )
            print("Transcrib", transcript)
            if not transcript or not transcript.text.strip():
                raise ValueError(
                    f"Audio transcription returned empty result for {file_name}"
                )

            logger.info(
                f"Successfully transcribed audio file: {file_name}, text length: {len(transcript.text)}"
            )
            return transcript.text

    except Exception as e:
        logger.error(
            "Failed to preprocess %s file '%s': %s", preprocess_type, file_name, e
        )

    return ""


def extract_structured_info_3(
    query: str,
    schema: Any,
    file_name: str | None = None,
    vector_store_id: str | None = None,  # Keep parameter but don't use it
    retries: int = 3,
    backoff_factor: float = 1.5,
) -> Any | None:
    """
    Extracts structured info from a model WITHOUT vector store.
    """

    config = _get_config(file_name)
    model_name = config["model"]
    # Remove file_search dependency
    

    attempt = 0
    while attempt < retries:
        try:
            api_params = {
                "model": model_name,
                "text_format": schema,
            }

            # 🔹 Handle different file types (SIMPLIFIED)
            if config["preprocess"] in {"excel", "csv", "audio"} and file_name:
                extracted_text = _preprocess_file(file_name, config["preprocess"])
                if not extracted_text:
                    raise ValueError(f"Preprocessing failed for file {file_name}")
                api_params["input"] = (
                    f"{query}\n\nHere is the content from the provided file:\n{extracted_text}"
                )

            elif config["preprocess"] == "image" and file_name:
                base64_image = encode_image_to_base64(file_name)
                if not base64_image:
                    raise ValueError(f"Could not encode image to base64: {file_name}")

                api_params["input"] = [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": query},
                            {
                                "type": "input_image",
                                "image_url": f"data:image/jpeg;base64,{base64_image}",
                            },
                        ],
                    }
                ]
            else:
                api_params["input"] = query

            # 🔹 REMOVED: File search and vector store tools
            # No need for vector store tools anymore

            # 🔹 Make API call
            print(api_params)
            response = client.responses.parse(**api_params)
            print("response", response)
            if response and response.output_parsed is not None:
                logger.info("Successfully parsed structured data.")
                return response.output_parsed

        except (ValidationError, ValueError) as e:
            logger.warning("Validation/model error: %s", e)
            raise ValueError("Model returned null/empty response.")
        except APIError as e:
            logger.warning("API error: %s", e)
        except Exception as e:
            logger.warning("Unexpected error: %s", e)

        attempt += 1
        if attempt < retries:
            wait_time = backoff_factor**attempt
            logger.info("Retrying in %.2f seconds...", wait_time)
            time.sleep(wait_time)

    if issubclass(schema, BaseModel):
        try:
            return schema.model_construct()
        except Exception as e:
            logger.error("Could not construct empty schema instance: %s", e)
            return None

    return None