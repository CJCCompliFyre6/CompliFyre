# Compliyier Backend Setup

This guide will help you set up and run the Compliyier backend application.

## Prerequisites

- Python 3.8 or higher
- pip (Python package installer)
- MySQL database

## Setup Instructions

### 1. Create and Activate Virtual Environment

```bash
# Create a virtual environment
python -m venv venv

# Activate virtual environment
# On Windows
venv\Scripts\activate
# On Linux/Mac
source venv/bin/activate
```

### 2. Install Dependencies

```bash
# Install required packages
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the root directory with the following content:

```plaintext
# Flask Configuration
FLASK_APP=run.py
FLASK_ENV=development
SECRET_KEY=your-secret-key-here

# Database Configuration
SQLALCHEMY_DATABASE_URI=mysql+pymysql://username:password@localhost/database_name
SQLALCHEMY_TRACK_MODIFICATIONS=False

# Other Configurations
UPLOAD_FOLDER=uploads
MAX_CONTENT_LENGTH=16777216
```

Replace `username`, `password`, and `database_name` with your MySQL database credentials.

### 4. Database Setup and Migrations

```bash
# Initialize migrations directory (if not already created)
flask db init

# Generate migration
flask db migrate -m "Initial migration"

# Apply migrations to database
flask db upgrade
```

### 5. Running the Application

```bash
# Run the Flask application
flask run

# For development with debug mode
flask run --debug
```

The application will be available at `http://localhost:5000`

## Project Structure

```
backend/
├── app/
│   ├── models/         # Database models
│   ├── routes/         # Route handlers
│   ├── services/       # Business logic
│   ├── templates/      # HTML templates
│   └── utils/          # Utility functions
├── migrations/         # Database migrations
├── requirements.txt    # Project dependencies
└── run.py             # Application entry point
```

## Additional Commands

```bash
# Generate new migration after model changes
flask db migrate -m "Description of changes"

# implement the migration
flask db upgradde

# View migration history
flask db history

# Rollback last migration
flask db downgrade

# View current migration state
flask db current
```

## Troubleshooting

1. If you encounter database connection issues, verify your MySQL service is running and credentials are correct in `.env`

2. For migration errors, ensure your database exists and is properly configured

3. If packages are missing, run `pip install -r requirements.txt` again

4. For permission errors in the uploads folder, ensure proper write permissions are set

## Development Guidelines

1. Always create new migrations for database changes
2. Keep environment variables in `.env` (never commit this file)
3. Use virtual environment to manage dependencies
4. Follow PEP 8 style guide for Python code