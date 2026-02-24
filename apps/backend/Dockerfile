FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY apps/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY apps/backend/app/ ./app/

# Copy frontend static files
COPY apps/frontend/ ./static/

# Run with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
