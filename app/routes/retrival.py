from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required
# from app import limiter
from app.services.pdf_service import PDFService
from app.utils.exceptions import PDFServiceError, URLValidationError
from marshmallow import Schema, fields, ValidationError
import os, json
from app.models.download import File

retrival_bp = Blueprint("retrive", __name__)


class URLSchema(Schema):
    url = fields.URL(required=True)


@retrival_bp.route("/retrive_pdf", methods=["POST"])
@login_required
def pdf_retrive():
    if "file" not in request.files:
        return jsonify({"error": "No file part in the request"}), 400

    try:
        file = request.files["file"]

        if file.filename == "":
            return jsonify({"error": "No selected file"}), 400

        if not file or not file.filename.lower().endswith(".pdf"):
            return jsonify({"error": "File is not a PDF"}), 400

        filename = f"{os.urandom(8).hex()}.pdf"
        uploads_dir = os.path.join(os.getcwd(), "uploads")
        save_path = os.path.join(uploads_dir, filename)

        file.save(save_path)

        pdf_service = PDFService()

        text = pdf_service.extract_text_from_pdf(save_path)
        analyzed_data = pdf_service.analyze_document(text)
        claus_data = pdf_service.retrive_clause(text)
        print(claus_data)
        json_data = json.loads(f"""{analyzed_data}""")
        claus_json = json.loads(f"""{claus_data}""")
        pdf_service.save_pdf_file(file, json_data, claus_json, save_path)
        return jsonify({"analyzed_data": json_data}), 200

    except PDFServiceError as err:
        return jsonify({"error": str(err)}), 400
    except Exception as err:
        current_app.logger.error(f"Error processing PDF: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@retrival_bp.route("/retrive_clause_guidlines", methods=["POST"])
@login_required
def clause_guidlines_retrive():
    if "file" not in request.files:
        return jsonify({"error": "No file part in the request"}), 400

    try:
        file = request.files["file"]

        if file.filename == "":
            return jsonify({"error": "No selected file"}), 400

        if not file or not file.filename.lower().endswith(".pdf"):
            return jsonify({"error": "File is not a PDF"}), 400

        filename = f"{os.urandom(8).hex()}.pdf"
        uploads_dir = os.path.join(os.getcwd(), "uploads")
        save_path = os.path.join(uploads_dir, filename)

        file.save(save_path)

        pdf_service = PDFService()

        text = pdf_service.extract_text_from_pdf(save_path)
        analyzed_data = pdf_service.retrive_clause_guidelines(text)
        # claus_data = pdf_service.retrive_clause(text)
        # json_data = json.loads(f'''{analyzed_data}''')
        # claus_json = json.loads(f'''{claus_data}''')
        # pdf_service.save_pdf_file(file,json_data,claus_json, save_path)
        return jsonify({"analyzed_data": analyzed_data}), 200

    except PDFServiceError as err:
        return jsonify({"error": str(err)}), 400
    except Exception as err:
        current_app.logger.error(f"Error processing PDF: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@retrival_bp.route("/retrive_regulatory_complience", methods=["POST"])
@login_required
def regulatory_complience_retrive():
    if "file" not in request.files:
        return jsonify({"error": "No file part in the request"}), 400

    try:
        file = request.files["file"]

        if file.filename == "":
            return jsonify({"error": "No selected file"}), 400

        if not file or not file.filename.lower().endswith(".pdf"):
            return jsonify({"error": "File is not a PDF"}), 400

        filename = f"{os.urandom(8).hex()}.pdf"
        uploads_dir = os.path.join(os.getcwd(), "uploads")
        save_path = os.path.join(uploads_dir, filename)

        file.save(save_path)

        pdf_service = PDFService()

        text = pdf_service.extract_text_from_pdf(save_path)
        analyzed_data = pdf_service.retrive_regulatory_complience(text)
        # claus_data = pdf_service.retrive_clause(text)
        json_data = json.loads(f"""{analyzed_data}""")
        # claus_json = json.loads(f'''{claus_data}''')
        # pdf_service.save_pdf_file(file,json_data,claus_json, save_path)
        return jsonify({"analyzed_data": json_data}), 200

    except PDFServiceError as err:
        return jsonify({"error": str(err)}), 400
    except Exception as err:
        current_app.logger.error(f"Error processing PDF: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@retrival_bp.route("/activity_redundancy", methods=["POST"])
@login_required
def activity_redundancy():
    if "file" not in request.files:
        return jsonify({"error": "No file part in the request"}), 400

    try:
        file = request.files["file"]

        if file.filename == "":
            return jsonify({"error": "No selected file"}), 400

        if not file or not file.filename.lower().endswith(".pdf"):
            return jsonify({"error": "File is not a PDF"}), 400

        filename = f"{os.urandom(8).hex()}.pdf"
        uploads_dir = os.path.join(os.getcwd(), "uploads")
        save_path = os.path.join(uploads_dir, filename)

        file.save(save_path)

        pdf_service = PDFService()

        text = pdf_service.extract_text_from_pdf(save_path)
        analyzed_data = pdf_service.activityMapping_redundancyIdentification(text)
        # claus_data = pdf_service.retrive_clause(text)
        json_data = json.loads(f"""{analyzed_data}""")
        # claus_json = json.loads(f'''{claus_data}''')
        # pdf_service.save_pdf_file(file,json_data,claus_json, save_path)
        return jsonify({"analyzed_data": json_data}), 200

    except PDFServiceError as err:
        return jsonify({"error": str(err)}), 400
    except Exception as err:
        current_app.logger.error(f"Error processing PDF: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@retrival_bp.route("/get_clause/<int:id>", methods=["POST"])
@login_required
def get_clause(id):
    try:
        pdf_service = PDFService()
        file = pdf_service.get_file_data(id)
        file_url = file.path
        text = pdf_service.extract_text_from_pdf(file_url)
        claus_data = pdf_service.retrive_clause(text)
        claus_json = json.loads(f"""{claus_data}""")
        pdf_service.update_file_data(id, claus_json)
        return jsonify({"Updated data": claus_json}), 200
    except Exception as err:
        current_app.logger.error(f"Error updating clause PDF: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@retrival_bp.route("/get_clause_data/<int:id>", methods=["GET"])
@login_required
def get_clause_data(id):
    try:
        pdf_service = PDFService()
        file = pdf_service.get_file_data(id)
        if not file:
            raise ValueError("File not found")

        # Convert the SQLAlchemy object to a dictionary
        file_data = {
            "id": file.id,
            "data": file.data,
            "clause": file.clause,
        }
        return jsonify({"Updated data": file_data}), 200
    except Exception as err:
        current_app.logger.error(f"Error getting clause PDF: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@retrival_bp.route("/analyze_pdf", methods=["POST"])
@login_required
def analyze_retrive():
    if not request.json:
        return jsonify({"error": "No data provided"}), 400
    schema = URLSchema()

    try:
        data = schema.load(request.json)
        pdf_service = PDFService()

        if not data or not pdf_service.validate_url(data["url"]):
            return jsonify({"error": "Invalid or inaccessible URL"}), 400

        filename = f"{os.urandom(8).hex()}.pdf"
        uploads_dir = os.path.join(os.getcwd(), "uploads")
        save_path = os.path.join(uploads_dir, filename)
        download = pdf_service.download_pdf(data["url"], save_path)

        text = pdf_service.extract_text_from_pdf(save_path)

        analyzed_data = pdf_service.analyze_document(text)
        claus_data = pdf_service.retrive_clause(text)
        json_data = json.loads(f"""{analyzed_data}""")
        claus_json = json.loads(f"""{claus_data}""")
        pdf_service.save_details(
            download["hash"], download["path"], download["size"], json_data, claus_json
        )
        return jsonify({"analyzed_data": json_data}), 200

    except ValidationError as err:
        return jsonify(err.messages), 400
    except PDFServiceError as err:
        return jsonify({"error": str(err)}), 400
    except Exception as err:
        current_app.logger.error(f"Error Processing PDF: {str(err)}")
        return jsonify({"error": "Internal server error"}), 500


@retrival_bp.route("/get_all_files", methods=["GET"])
@login_required
def get_all_files():
    try:
        files = File.query.all()

        if not files:
            current_app.logger.info("No files found in the database.")
            return jsonify({"files": []}), 200  # Return an empty list if no files are found

        # Convert each file record to a dictionary
        files_list = [
            {
                "id": file.id,
                "hash": file.hash,
                "path": file.path,
                "size": file.size,
                "data": file.data,
                "created_at": file.created_at.isoformat() if file.created_at else None,
                "last_accessed": (
                    file.last_accessed.isoformat() if file.last_accessed else None
                ),
                "duplicate_count": file.duplicate_count,
            }
            for file in files
        ]

        return jsonify({"files": files_list}), 200

    except Exception as e:
        current_app.logger.error(f"Error retrieving files: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500
