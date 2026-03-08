# /backend/Dockerfile
FROM python:3.11-slim

# Install system dependencies, including Tesseract OCR!
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    gcc \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy your python requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# We don't copy the rest of the code here because docker-compose will "mirror" it for live-editing!

# Run the FastAPI server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]