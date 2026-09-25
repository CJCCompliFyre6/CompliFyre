from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required
from app.utils.permission_handler import role_required

# from app import limiter
from app.services.prompts import PromptService
from app.utils.exceptions import PDFServiceError, URLValidationError
from marshmallow import Schema, fields, ValidationError
import os, json

prompt_bp = Blueprint("prompt", __name__)


class URLSchema(Schema):
    url = fields.URL(required=True)


@prompt_bp.route("/get_all_prompt", methods=["GET"])
def get_all_prompt():
    prompt_service = PromptService()
    try:
        prompts = prompt_service.get_prompts()
        return jsonify({"prompts": [prompt.to_dict() for prompt in prompts]}), 200
    except Exception as err:
        current_app.logger.error(f"Error retrieving prompts: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@prompt_bp.route("/get_prompt/<int:prompt_id>", methods=["GET"])
def get_prompt(prompt_id):
    prompt_service = PromptService()
    try:
        prompt = prompt_service.get_prompt(prompt_id)
        return jsonify({"prompt": prompt.to_dict()}), 200
    except Exception as err:
        current_app.logger.error(f"Error retrieving prompt: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@prompt_bp.route("/create_prompt", methods=["POST"])
@login_required
@role_required("COMPLIFYRE")  # S-67: only COMPLIFYRE can create prompts
def create_prompt():

    if not request.json:
        return jsonify({"error": "No data provided"}), 400

    try:
        data = request.json
        prompt_service = PromptService()

        prompt = prompt_service.create_prompt(data["prompt"])
        # print(prompt.id)
        return jsonify({"prompt": prompt.prompt, "id": prompt.id}), 200
    except ValidationError as err:
        return jsonify(err.messages), 400
    except PDFServiceError as err:
        return jsonify({"error": str(err)}), 400
    except Exception as err:
        current_app.logger.error(f"Error creating prompt: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@prompt_bp.route("/delete_prompt/<int:prompt_id>", methods=["DELETE"])
@login_required
@role_required("COMPLIFYRE")  # S-67: only COMPLIFYRE can delete prompts
def delete_prompt(prompt_id):
    prompt_service = PromptService()
    try:
        prompt_service.delete_prompt(prompt_id)
        return jsonify({"message": "Prompt deleted successfully"}), 200
    except Exception as err:
        current_app.logger.error(f"Error deleting prompt: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@prompt_bp.route("/update_prompt/<int:prompt_id>", methods=["PUT"])
@login_required
@role_required("COMPLIFYRE")  # S-67: only COMPLIFYRE can update prompts
def update_prompt(prompt_id):
    if not request.json:
        return jsonify({"error": "No data provided"}), 400
    try:
        data = request.json
        prompt_service = PromptService()
        prompt = prompt_service.update_prompt(prompt_id, data["prompt"])
        return jsonify({"prompt": prompt.prompt}), 200
    except KeyError:
        return jsonify({"error": "Missing required fields in the request"}), 400
    except TypeError:
        return jsonify({"error": "Invalid data type provided"}), 400
    except ValidationError as err:
        return jsonify(err.messages), 400
    except PDFServiceError as err:
        return jsonify({"error": str(err)}), 400
    except Exception as err:
        current_app.logger.error(f"Error updating prompt: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500
