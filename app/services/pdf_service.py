# backend/app/services/pdf_service.py
from __future__ import annotations
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import hashlib
import os, re
from datetime import datetime, timezone
import logging
from app import db, client
from app.models.download import Download, File
from app.services.prompts import PromptService
import fitz
from app.services.prompt_service import PromptsText
import json
import requests
from app.models.download import *
from app.models.ai import *
from app.models.organization import OrganizationDepartments
from sqlalchemy.exc import IntegrityError

class PDFService(PromptsText):
    def __init__(self, cache_service=None):
        self.session = requests.Session()
        self.cache_service = cache_service
        self.logger = logging.getLogger(__name__)

    def validate_url(self, url: str) -> bool:
        """
        Validate if the given URL is well-formed and accessible.

        Args:
            url (str): The URL to validate

        Returns:
            bool: True if valid, False otherwise

        Raises:
            ValueError: If URL is malformed
        """
        try:
            result = urlparse(url)
            # print(result)
            if not all([result.scheme, result.netloc]):
                raise ValueError("Invalid URL format")

            # Check if URL is accessible
            response = self.session.head(url, allow_redirects=True, timeout=60)
            # print(response)
            return response.status_code == 200

        except requests.RequestException as e:
            self.logger.error(f"Error validating URL {url}: {str(e)}")
            return False

    def scan_for_pdfs(self, url: str) -> List[Dict]:
        """
        Scan webpage for PDF links and insert them into the database.

        Args:
            url (str): The webpage URL to scan

        Returns:
            List[Dict]: List of found PDFs with metadata

        Raises:
            requests.RequestException: If page cannot be accessed
        """
        pdf_links = []

        try:
            # Get webpage content
            response = self.session.get(url, timeout=600)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            # Find all links
            for link in soup.find_all("a"):
                href = link.get("href")
                if not href:
                    continue

                # Convert relative URLs to absolute
                full_url = urljoin(url, href)

                # Check if link points to PDF
                if self._is_pdf_link(full_url):
                    pdf_info = {
                        "url": full_url,
                        "title": link.get_text().strip() or os.path.basename(full_url),
                        "size": self._get_file_size(full_url),
                    }
                    pdf_links.append(pdf_info)

            # Insert PDF data into the database
            self.insert_pdf_data(pdf_links)

            return pdf_links

        except requests.RequestException as e:
            self.logger.error(f"Error scanning URL {url}: {str(e)}")
            raise


    def insert_pdf_data(self, pdf_links: List[Dict]):
        """
        Insert PDF metadata into the PolicyDocument table.

        Args:
            pdf_links (List[Dict]): List of PDF metadata dictionaries.
        """
        for pdf in pdf_links:
            try:
                # Create a new PolicyDocument object and insert into the database
                new_pdf = PolicyDocument(
                    url=pdf['url'],
                    title=pdf['title'],
                    size=pdf['size']
                )
                db.session.add(new_pdf)

                # Commit to the database
                db.session.commit()

            except IntegrityError:
                # If the PDF URL already exists in the database, skip it
                db.session.rollback()
                self.logger.warning(f"PDF already exists in the database: {pdf['url']}")
            except Exception as e:
                # Handle any other exceptions during insertion
                db.session.rollback()
                self.logger.error(f"Error inserting PDF {pdf['url']}: {str(e)}")


    def download_pdf(self, url: str, save_path: str) -> Dict:
        """
        Download a PDF file with progress tracking and verification.

        Args:
            url (str): The PDF URL
            save_path (str): Where to save the file

        Returns:
            Dict: Download result metadata

        Raises:
            requests.RequestException: If download fails
            ValueError: If file verification fails
        """
        try:
            # Check cache first if cache service is available
            if self.cache_service and (cached_path := self.cache_service.get(url)):
                return {
                    "path": cached_path,
                    "from_cache": True,
                    "size": os.path.getsize(cached_path),
                }

            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(save_path), exist_ok=True)

            # Download with progress tracking
            response = self.session.get(url, stream=True)
            response.raise_for_status()

            file_size = int(response.headers.get("content-length", 0))

            # Calculate hash while downloading
            sha256_hash = hashlib.sha256()

            with open(save_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        sha256_hash.update(chunk)

            file_hash = sha256_hash.hexdigest()

            # Verify download
            if not self._verify_pdf(save_path):
                os.remove(save_path)
                raise ValueError("Downloaded file is not a valid PDF")

            # # Save to database
            # file_record = File(
            #     hash=file_hash,
            #     path=save_path,
            #     size=file_size,
            #     data=json_data,
            #     created_at=datetime.now(timezone.utc),
            # )

            # download_record = Download(url=url, status="completed", data=json_data, file_hash=file_hash)

            # db.session.add(file_record)
            # db.session.add(download_record)
            # db.session.commit()

            # Update cache if available
            if self.cache_service:
                self.cache_service.set(url, save_path)

            return {
                "path": save_path,
                "hash": file_hash,
                "size": file_size,
                "from_cache": False,
            }

        except (requests.RequestException, IOError) as e:
            self.logger.error(f"Error downloading PDF from {url}: {str(e)}")

            # # Save failed download record
            # download_record = Download(url=url, status="failed", file_hash="")
            # db.session.add(download_record)
            # db.session.commit()

            raise

    def save_details(
        self,
        file_hash: str,
        save_path: str,
        file_size: str,
        json_data: Dict,
        clause_data,
    ) -> Dict:
        # 1. Create and add File and Download objects first
        file_record = File(
            hash=file_hash,
            path=save_path,
            size=file_size,
            data=json_data,
            clause=clause_data,
            created_at=datetime.now(timezone.utc),
        )

        download_record = Download(
            url=save_path,
            status="completed",
            data=json_data,
            clause=clause_data,
            file_hash=file_hash,
        )

        db.session.add(file_record)
        db.session.add(download_record)
        db.session.flush()  # This assigns IDs without committing

        # 2. Create Guidelines after File and Download are flushed
        guidelines = Guidelines(
            guideline_data=json_data,
            url_id=download_record.id,
            file_id=file_record.id,
        )

        db.session.add(guidelines)
        db.session.flush()  # Ensure guideline_id is available

        # 3. Add Clauses associated with Guidelines
        print(clause_data)
        clauses = []
        for clause_item in clause_data.get("requirements", []):
            clause = Clauses(
                clause_no=clause_item.get("clause_number"),
                clause_text=clause_item.get("clause_text"),
                guideline_id=guidelines.id,
            )
            clauses.append(clause)
            db.session.add(clause)

        # 4. Commit all changes
        db.session.commit()

        return {
            "status": "completed",
            "data": json_data,
            "url": save_path
        }


    def save_pdf_file(self, file, json_data: Dict, clause_data, url: str) -> Dict:
        """
        Process a PDF file with progress tracking and verification.

        Args:
            file (FileStorage): The uploaded file object
            url (str): The URL associated with the file (for record-keeping)

        Returns:
            Dict: Download result metadata

        Raises:
            ValueError: If file verification fails
        """
        try:
            # Validate json_data and clause_data
            if not isinstance(json_data, dict):
                raise ValueError(f"Expected json_data to be a dictionary, got {type(json_data)}")

            if not isinstance(clause_data, dict):
                raise ValueError(f"Expected clause_data to be a dictionary, got {type(clause_data)}")

            # for clause_item in clause_data.values():
            #     if not isinstance(clause_item, dict):
            #         raise ValueError(f"Each item in clause_data must be a dictionary, got {type(clause_item)}")
            #     if "clause_number" not in clause_item or "clause_text" not in clause_item:
            #         raise ValueError(f"Missing required keys in clause_data item: {clause_item}")

            # Calculate hash while reading the file content
            sha256_hash = hashlib.sha256()

            file_content = file.read()  # Read the entire file content
            sha256_hash.update(file_content)
            file_hash = sha256_hash.hexdigest()
            filename = f"{os.urandom(8).hex()}.pdf"
            save_path = os.path.join("uploads", filename)

            with open(save_path, "wb") as f:
                f.write(file_content)

            file_hash = sha256_hash.hexdigest()
            file_size = len(file_content)

            file_record = File(
                hash=file_hash,
                path=url,
                size=file_size,
                data=json_data,
                clause=clause_data,
                created_at=datetime.now(timezone.utc),
            )

            download_record = Download(
                url=url,
                status="completed",
                data=json_data,
                clause=clause_data,
                file_hash=file_hash,
            )
            db.session.add(file_record)
            db.session.add(download_record)
            db.session.flush()  # This assigns IDs without committing

            guidelines = Guidelines(
                guideline_data=json_data,
                url_id=download_record.id,
                file_id=file_record.id,
            )
            db.session.add(guidelines)
            db.session.flush()  # Ensure guideline_id is available

            clauses = []
            print(clause_data)
            for clause_item in clause_data['requirements']:
                clause = Clauses(
                    clause_no=clause_item["clause_number"],
                    clause_text=clause_item["clause_text"],
                    guideline_id=guidelines.id,
                )
                clauses.append(clause)
                db.session.add(clause)

            # db.session.add(file_record)
            # db.session.add(download_record)
            # db.session.add(guidelines)
            db.session.commit()

            return {
                "hash": file_hash,
                "size": file_size,
                "from_cache": False,
            }

        except Exception as e:
            self.logger.error(f"Error processing PDF: {str(e)}")

            download_record = Download(url=url, status="failed", file_hash="")
            db.session.add(download_record)
            db.session.commit()

            raise

    def _is_pdf_link(self, url: str) -> bool:
        """Check if URL points to a PDF file."""
        # Check file extension
        if url.lower().endswith(".pdf"):
            return True

        try:
            # Check Content-Type header
            response = self.session.head(url, allow_redirects=True, timeout=5)
            content_type = response.headers.get("Content-Type", "").lower()
            return "application/pdf" in content_type

        except requests.RequestException:
            return False

    def _get_file_size(self, url: str) -> Optional[int]:
        """Get file size from Content-Length header."""
        try:
            response = self.session.head(url, allow_redirects=True, timeout=5)
            return int(response.headers.get("Content-Length", 0))
        except (requests.RequestException, ValueError):
            return None

    def _verify_pdf(self, file_path: str) -> bool:
        """Verify if file is a valid PDF."""
        try:
            with open(file_path, "rb") as f:
                # Check PDF magic number
                header = f.read(4)
                return header == b"%PDF"
        except IOError:
            return False

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract text from a PDF file."""
        doc = fitz.open(pdf_path)
        print(doc)
        text = ""
        for page in doc:
            text += page.get_text("text") + "\n"
        return text



    def analyze_document(self, document_text: str) -> str:
        """Send extracted text to OpenAI GPT-4 for structured analysis."""
        prompt_service = PromptService()
        prompt_template = self.prompt_1
        # print('new_service',prompt_template.prompt)
        prompt = f"""
                {prompt_template}
                \"\"\"
                {document_text}
                \"\"\"
                """

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful AI that extracts structured information from regulatory documents.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        pattern = r"```json(.*?)```"

        result = response.choices[0].message.content
        # print(result)
        matches = re.findall(pattern, result, re.DOTALL)
        return matches[0]

    def retrive_clause(self, text: str) -> str:
        """Retrieve clause information from PDF ."""
        prompt = f"""
                {self.prompt_2}
                \"\"\"
                {text}
                """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful AI that extracts structured information from regulatory documents.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        pattern = r"```json(.*?)```"

        result = response.choices[0].message.content
        # print(result)
        matches = re.findall(pattern, result, re.DOTALL)
        return matches[0]

    def retrive_clause_guidelines(self, text: str) -> str:
        """Retrieve clause information from PDF ."""
        prompt = f"""
                {self.prompt_3}
                \"\"\"
                {text}
                """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful AI that extracts structured information from regulatory documents.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        # pattern = r'```json(.*?)```'

        result = response.choices[0].message.content
        # print(result)
        # matches = re.findall(pattern, result, re.DOTALL)
        return result

    def retrive_regulatory_complience(self,clause, text: str) -> str:
        """Retrieve clause information from PDF ."""
        depart = OrganizationDepartments.query.all()
        
        department_list = [{'department_id':d.department_id, 'department_name':d.department_name, 'process':d.process_name, 'sub_process':d.sub_process} for d in depart]
        print(department_list)
        prompt_activity = self.prompt_4(clause, department_list)
        prompt = f"""
                {prompt_activity}
                \"\"\"
                {text}
                """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful AI that extracts structured information from regulatory documents.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        pattern = r"```json(.*?)```"

        result = response.choices[0].message.content
        print(result)
        matches = re.findall(pattern, result, re.DOTALL)
        return matches[0]


    def retrive_activity(self, clause, activity, text: str) -> str:
        """Retrieve clause information from PDF ."""
        prompt_activity = self.prompt_5(clause,activity)
        prompt = f"""
                {prompt_activity}
                \"\"\"
                {text}
                """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful AI that extracts structured information from regulatory documents.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        pattern = r"```json(.*?)```"

        result = response.choices[0].message.content
        # print(result)
        matches = re.findall(pattern, result, re.DOTALL)
        return matches[0]

    def activityMapping_redundancyIdentification(self, text: str) -> str:
        """Retrieve clause information from PDF ."""
        prompt = f"""
                {self.prompt_5}
                \"\"\"
                {text}
                """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful AI that extracts structured information from regulatory documents.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        pattern = r"```json(.*?)```"

        result = response.choices[0].message.content
        # print(result)
        matches = re.findall(pattern, result, re.DOTALL)
        return matches[0]
    
    def test_procedures(self, clause, activity, text: str) -> str:
        """Retrieve clause information from PDF ."""
        prompt_activity = self.prompt_6(clause,activity)
        prompt = f"""
                {prompt_activity}
                \"\"\"
                {text}
                """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful AI that extracts structured information from regulatory documents.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        pattern = r"```json(.*?)```"

        result = response.choices[0].message.content
        # print(result)
        matches = re.findall(pattern, result, re.DOTALL)
        return matches[0]

    def get_file_data(self, id: int) -> Dict:
        try:
            file = File.query.get(id)
            return file
        except Exception as e:
            self.logger.error(f"Error retrieving file {id}: {str(e)}")
            raise

    def update_file_data(self, id: int, text: Dict) -> Dict:
        try:
            file = File.query.get(id)
            file.clause = text
            file.timestamp = datetime.now(timezone.utc)
            db.session.commit()
            return file
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error Updating clause at {id}: {str(e)}")
            raise
