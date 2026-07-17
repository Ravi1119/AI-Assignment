FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for PDF processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmupdf-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Handle corporate SSL/proxy issues
ENV PIP_TRUSTED_HOST="pypi.org pypi.python.org files.pythonhosted.org"

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --trusted-host pypi.org --trusted-host pypi.python.org --trusted-host files.pythonhosted.org -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY data/ ./data/
COPY tests/ ./tests/
COPY demo_flow.py .

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
