from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required
from app import limiter
from app.services.pdf_service import PDFService
from app.utils.exceptions import PDFServiceError, URLValidationError
from marshmallow import Schema, fields, ValidationError
import os

download_bp = Blueprint("download", __name__)


class URLSchema(Schema):
    url = fields.URL(required=True)


@download_bp.route("/scan", methods=["POST"])
@login_required
@limiter.limit("100 per minute")
def scan_pdfs():
    schema = URLSchema()
    try:
        if not request.json:
            return jsonify({"error": "No data provided"}), 400
        data = schema.load(request.json)
        pdf_service = PDFService()

        if data is None:
            return jsonify({"error": "Invalid or inaccessible URL Data"}), 400

        if not pdf_service.validate_url(data["url"]):
            return jsonify({"error": "Invalid or inaccessible URL Invalid"}), 400

        pdf_links = pdf_service.scan_for_pdfs(data["url"])
        print(pdf_links)
        print(data["url"])
        return (
            jsonify(
                {"url": data["url"], "pdfs_found": len(pdf_links), "pdfs": pdf_links}
            ),
            200,
        )

    except ValidationError as err:
        return jsonify(err.messages), 400
    except PDFServiceError as err:
        return jsonify({"error": str(err)}), 400
    except Exception as err:
        current_app.logger.error(f"Error scanning PDFs: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@download_bp.route("/download", methods=["POST"])
@login_required
@limiter.limit("5 per minute")
def download_pdf():
    if not request.json:
        return jsonify({"error": "No data provided"}), 400
    schema = URLSchema()
    try:
        data = schema.load(request.json)
        pdf_service = PDFService()

        if not data or not pdf_service.validate_url(data["url"]):
            return jsonify({"error": "Invalid or inaccessible URL"}), 400

        # Create a unique filename
        filename = f"{os.urandom(8).hex()}.pdf"
        save_path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)

        result = pdf_service.download_pdf(data["url"], save_path)

        return jsonify({"message": "Download successful", "file_info": result}), 200

    except ValidationError as err:
        return jsonify(err.messages), 400
    except PDFServiceError as err:
        return jsonify({"error": str(err)}), 400
    except Exception as err:
        current_app.logger.error(f"Error downloading PDF: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500
