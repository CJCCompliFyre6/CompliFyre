# Contributing to Complifyer

## Project Overview
Complifyer is a compliance management system designed to streamline the process of managing guidelines, clauses, and compliance activities. The project includes features such as document analysis, task extraction, and activity tracking. It is built using Python (Flask) for the backend and HTML/CSS/JavaScript for the frontend.

## Folder Structure
Here is an overview of the key folders and files in the project:

- **app/**: Contains the main application code.
  - **models/**: Defines the database models, such as:
    - `AIPrompts`: Stores AI-generated prompts.
    - `Guidelines` and `Clauses`: Manage guidelines and their associated clauses.
    - `ComplianceActivities`: Tracks compliance-related activities.
  - **routes/**: Contains route handlers for various functionalities, including:
    - `download.py`: Handles file download operations.
    - `prompts.py`: Manages AI prompt-related routes.
    - `retrival.py`: Handles data retrieval operations.
    - **audit/** and **re/**: Subfolders for audit and RE-specific routes.
  - **services/**: Includes service files for handling business logic, such as:
    - `pdf_service.py`: Processes PDF files for data extraction.
    - `prompt_service.py`: Manages AI prompt operations.
  - **templates/**: Stores HTML templates for the frontend, including:
    - `dashboards/`: Contains dashboard-related templates.
    - `type.html`: A generic template for displaying types.
- **docker/**: Contains Docker configuration files for setting up the development and production environments.
  - `docker-compose.yml`: Defines services for the application.
  - `Dockerfile.backend`: Dockerfile for the backend service.
  - `nginx.conf`: Configuration for the Nginx server.
- **uploads/**: Stores uploaded files, such as PDFs.
- **migrations/**: Manages database migrations using Alembic.
  - `versions/`: Contains migration scripts.
- **instance/**: Stores instance-specific files, such as the SQLite database.
- **requirements.txt**: Lists the Python dependencies for the project.
- **run.py**: The entry point for running the Flask application.

## Setup Instructions
Follow these steps to set up the development environment:

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd compliyier/backend
   ```

2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set up the database:
   - Create a database (e.g., `compliyier_db`).
   - Run migrations to set up the schema:
     ```bash
     alembic upgrade head
     ```

4. Start the application:
   ```bash
   python run.py
   ```

5. Access the application at `http://localhost:5000`.

## Key Features Implemented
- **Database Models**:
  - `AIPrompts`: Stores AI prompt data.
  - `Guidelines` and `Clauses`: Manage guidelines and their associated clauses.
  - `ComplianceActivities`: Tracks compliance-related activities.
- **Frontend**:
  - HTML templates for dashboards and forms.
  - Loading spinner functionality for user feedback during long-running operations.
- **Backend**:
  - Routes for handling guideline and clause operations.
  - Services for PDF processing and prompt management.
  - Integration with AI for generating prompts.

## Coding Standards
- Follow PEP 8 guidelines for Python code.
- Use meaningful variable and function names.
- Write comments and docstrings to explain complex logic.
- Keep functions and methods small and focused.
- Use consistent indentation and formatting for HTML, CSS, and JavaScript.

## How to Contribute
1. **Fork the Repository**: Create your own fork of the repository.
2. **Create a Branch**: Create a new branch for your feature or bug fix:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Make Changes**: Implement your changes and write tests if applicable.
4. **Run Tests**: Ensure all tests pass before submitting your changes.
5. **Submit a Pull Request**: Push your branch to your fork and create a pull request.

## Testing
- Use the provided test cases or add new ones to ensure your changes work as expected.
- Run tests using the following command:
  ```bash
  pytest
  ```

## Development Tips
- Use virtual environments to manage dependencies:
  ```bash
  python -m venv venv
  source venv/bin/activate
  ```
- Use Flask's debug mode during development:
  ```bash
  export FLASK_ENV=development
  python run.py
  ```
- Use Docker for containerized development and deployment.

## Contact
For any questions or issues, please contact the project maintainer or create an issue in the repository.