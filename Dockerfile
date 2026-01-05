# LEAF DSS - Dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for GeoPandas
RUN apt-get update && apt-get install -y \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Set GDAL environment variables
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

# Copy requirements first for caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy data files from parent directory
COPY ../4DSS_VAR_2.0.* ./data/
COPY ../DSS_input2.csv ./data/

# Set environment variables
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV SHAPE_RESTORE_SHX=YES

# Expose port
EXPOSE 5000

# Run with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "120", "app:app"]
