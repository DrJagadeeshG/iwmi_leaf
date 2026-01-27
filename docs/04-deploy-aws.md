# Future Deployment: AWS

## Overview

For production workloads with higher availability, scalability, and performance requirements, AWS provides multiple deployment options. This guide covers recommended approaches for deploying LEAF DSS on AWS.

## Deployment Options

### Option 1: AWS Elastic Beanstalk (Recommended for Simplicity)

Elastic Beanstalk provides managed infrastructure with auto-scaling.

#### Pros
- Easy deployment and management
- Auto-scaling built-in
- Load balancing included
- Managed platform updates

#### Cons
- Less control over infrastructure
- Can be more expensive than EC2

#### Setup Steps

1. **Install EB CLI**
   ```bash
   pip install awsebcli
   ```

2. **Initialize Elastic Beanstalk**
   ```bash
   cd leaf_flask
   eb init -p docker leaf-dss --region ap-south-1
   ```

3. **Create Environment**
   ```bash
   eb create leaf-dss-prod --instance-type t3.small
   ```

4. **Deploy**
   ```bash
   eb deploy
   ```

#### Configuration File: `.ebextensions/01_packages.config`
```yaml
packages:
  yum:
    gdal-devel: []
    geos-devel: []
    proj-devel: []
```

### Option 2: Amazon ECS with Fargate (Recommended for Scalability)

Serverless container deployment with automatic scaling.

#### Architecture
```
                    ┌─────────────────┐
                    │   Route 53      │
                    │   (DNS)         │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  CloudFront     │
                    │  (CDN)          │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Application    │
                    │  Load Balancer  │
                    └────────┬────────┘
                             │
           ┌─────────────────┼─────────────────┐
           │                 │                 │
    ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐
    │   Fargate   │   │   Fargate   │   │   Fargate   │
    │   Task 1    │   │   Task 2    │   │   Task 3    │
    └─────────────┘   └─────────────┘   └─────────────┘
```

#### Setup Steps

1. **Create ECR Repository**
   ```bash
   aws ecr create-repository --repository-name leaf-dss
   ```

2. **Build and Push Docker Image**
   ```bash
   # Login to ECR
   aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin YOUR_ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com

   # Build image
   docker build -t leaf-dss .

   # Tag and push
   docker tag leaf-dss:latest YOUR_ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com/leaf-dss:latest
   docker push YOUR_ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com/leaf-dss:latest
   ```

3. **Create ECS Cluster**
   ```bash
   aws ecs create-cluster --cluster-name leaf-dss-cluster
   ```

4. **Create Task Definition**: `task-definition.json`
   ```json
   {
     "family": "leaf-dss",
     "networkMode": "awsvpc",
     "requiresCompatibilities": ["FARGATE"],
     "cpu": "512",
     "memory": "1024",
     "containerDefinitions": [
       {
         "name": "leaf-dss",
         "image": "YOUR_ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com/leaf-dss:latest",
         "portMappings": [
           {
             "containerPort": 10000,
             "protocol": "tcp"
           }
         ],
         "environment": [
           {"name": "FLASK_ENV", "value": "production"}
         ],
         "logConfiguration": {
           "logDriver": "awslogs",
           "options": {
             "awslogs-group": "/ecs/leaf-dss",
             "awslogs-region": "ap-south-1",
             "awslogs-stream-prefix": "ecs"
           }
         }
       }
     ]
   }
   ```

5. **Create Service with ALB**
   ```bash
   aws ecs create-service \
     --cluster leaf-dss-cluster \
     --service-name leaf-dss-service \
     --task-definition leaf-dss \
     --desired-count 2 \
     --launch-type FARGATE \
     --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=ENABLED}"
   ```

### Option 3: EC2 with Docker (Most Control)

Direct EC2 deployment for maximum control.

#### Setup Steps

1. **Launch EC2 Instance**
   - AMI: Amazon Linux 2023
   - Instance Type: t3.small (minimum)
   - Storage: 20 GB
   - Security Group: Allow ports 22, 80, 443

2. **Install Dependencies**
   ```bash
   sudo yum update -y
   sudo yum install -y docker git
   sudo systemctl start docker
   sudo usermod -aG docker ec2-user
   ```

3. **Clone and Deploy**
   ```bash
   git clone https://github.com/DrJagadeeshG/iwmi_leaf.git
   cd iwmi_leaf
   docker build -t leaf-dss .
   docker run -d -p 80:10000 --name leaf-dss leaf-dss
   ```

4. **Setup Nginx (Optional - for SSL)**
   ```bash
   sudo yum install -y nginx
   sudo systemctl start nginx
   ```

   Nginx config (`/etc/nginx/conf.d/leaf-dss.conf`):
   ```nginx
   server {
       listen 80;
       server_name leaf.yourdomain.com;

       location / {
           proxy_pass http://localhost:10000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }
   }
   ```

## Cost Comparison

| Service | Estimated Monthly Cost | Best For |
|---------|----------------------|----------|
| Elastic Beanstalk (t3.small) | $15-25 | Simple deployment |
| ECS Fargate (0.5 vCPU, 1GB) | $20-40 | Scalable production |
| EC2 (t3.small) | $15-20 | Maximum control |
| EC2 Spot Instance | $5-10 | Cost-sensitive, fault-tolerant |

## Recommended Architecture for Production

```
┌─────────────────────────────────────────────────────────────────┐
│                         AWS Cloud                                │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │  Route 53    │───▶│  CloudFront  │───▶│     ALB      │      │
│  │  (DNS)       │    │  (CDN)       │    │              │      │
│  └──────────────┘    └──────────────┘    └──────┬───────┘      │
│                                                  │               │
│                           ┌──────────────────────┼──────┐       │
│                           │        ECS Fargate   │      │       │
│                           │  ┌─────────┐  ┌─────────┐  │       │
│                           │  │ Task 1  │  │ Task 2  │  │       │
│                           │  └─────────┘  └─────────┘  │       │
│                           └─────────────────────────────┘       │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │     S3       │    │  CloudWatch  │    │    ECR       │      │
│  │ (Static/Data)│    │  (Logs)      │    │  (Images)    │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## CI/CD Pipeline with GitHub Actions

Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy to AWS

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v2
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ap-south-1

      - name: Login to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v1

      - name: Build, tag, and push image to Amazon ECR
        env:
          ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
          ECR_REPOSITORY: leaf-dss
          IMAGE_TAG: ${{ github.sha }}
        run: |
          docker build -t $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG .
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG

      - name: Update ECS service
        run: |
          aws ecs update-service --cluster leaf-dss-cluster --service leaf-dss-service --force-new-deployment
```

## Security Best Practices

1. **Use IAM Roles** - Never hardcode credentials
2. **Enable HTTPS** - Use ACM for SSL certificates
3. **VPC Isolation** - Deploy in private subnets
4. **Security Groups** - Restrict inbound traffic
5. **Secrets Manager** - Store sensitive configuration
6. **WAF** - Protect against common web attacks

## Monitoring & Logging

1. **CloudWatch Logs** - Centralized logging
2. **CloudWatch Alarms** - Set up alerts for errors/latency
3. **X-Ray** - Distributed tracing (optional)
4. **Health Checks** - ALB health checks on `/health` endpoint
