# Deploying LEAF DSS to Render

## Overview

Render is a cloud platform that offers easy deployment with automatic builds from GitHub. This guide covers deploying LEAF DSS using Docker on Render's free tier.

## Prerequisites

- GitHub repository with the LEAF DSS code
- Render account (https://render.com)

## Files Required for Deployment

### 1. Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for GeoPandas
RUN apt-get update && apt-get install -y \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV SHAPE_RESTORE_SHX=YES

EXPOSE 10000

CMD gunicorn --bind 0.0.0.0:${PORT:-10000} --workers 2 --threads 4 --timeout 120 app:app
```

### 2. render.yaml (Optional - for Infrastructure as Code)

```yaml
services:
  - type: web
    name: leaf-dss
    runtime: docker
    envVars:
      - key: PYTHON_VERSION
        value: 3.11.0
```

### 3. requirements.txt

```
flask>=3.0.0
flask-cors>=4.0.0
gunicorn>=21.2.0
pandas>=2.0.0
numpy>=1.24.0
geopandas>=0.14.0
shapely>=2.0.0
pyproj>=3.6.0
fiona>=1.9.0
```

## Deployment Steps

### Step 1: Push Code to GitHub

```bash
cd /path/to/leaf_flask
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/iwmi_leaf.git
git push -u origin main
```

### Step 2: Create Render Account

1. Go to https://render.com
2. Sign up using GitHub (recommended for easy repo connection)

### Step 3: Create New Web Service

1. Click **New** → **Web Service**
2. Connect your GitHub repository
3. Select the `iwmi_leaf` repository

### Step 4: Configure Service

| Setting | Value |
|---------|-------|
| Name | `leaf-dss` (or your preferred name) |
| Region | Oregon (US West) or nearest to users |
| Branch | `main` |
| Runtime | Docker |
| Instance Type | Free |

### Step 5: Deploy

1. Click **Create Web Service**
2. Wait for build to complete (5-10 minutes for first build)
3. Access your app at `https://leaf-dss.onrender.com`

## Build Time Considerations

The first build takes longer due to:
- Installing system dependencies (GDAL, GEOS, PROJ)
- Compiling GeoPandas and related packages

Subsequent builds use cached layers and are faster.

## Free Tier Limitations

| Limitation | Description |
|------------|-------------|
| Spin Down | Instance sleeps after 15 minutes of inactivity |
| Cold Start | First request after sleep takes 30-60 seconds |
| RAM | 512 MB |
| CPU | 0.1 CPU |
| Bandwidth | 100 GB/month |

## Monitoring

### Health Check

Render automatically monitors the `/health` endpoint:
```
https://leaf-dss.onrender.com/health
```

### Logs

View logs in Render dashboard:
1. Go to your service
2. Click **Logs** tab
3. Filter by time or search for errors

## Updating the Application

### Automatic Deployment

By default, Render auto-deploys when you push to the `main` branch:

```bash
git add .
git commit -m "Update feature"
git push
```

### Manual Deployment

1. Go to Render dashboard
2. Click **Manual Deploy** → **Deploy latest commit**

## Environment Variables

Set environment variables in Render dashboard:

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Flask secret key for sessions |
| `FLASK_ENV` | Set to `production` |

## Custom Domain (Optional)

1. Go to **Settings** → **Custom Domains**
2. Add your domain (e.g., `leaf.iwmi.org`)
3. Configure DNS with provided CNAME record

## Troubleshooting

### Build Fails

1. Check **Logs** for error messages
2. Common issues:
   - Missing system dependencies → Update Dockerfile
   - Package conflicts → Check requirements.txt versions

### Application Crashes

1. Check application logs
2. Common issues:
   - Memory exceeded → Optimize data loading
   - File not found → Verify data paths

### Slow Response

1. Free tier has limited resources
2. Consider upgrading to paid tier for production use
