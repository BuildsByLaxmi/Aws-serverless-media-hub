# Infrastructure Deployment Notes & Runbook
**AWS Serverless Media Transcoder and Thumbnail Pipeline**  
**Lead Owner**: Person 1 (Infrastructure & Delivery Lead)

---

## 1. Overview
This document provides complete instructions for deploying, configuring, and verifying the AWS infrastructure required for the media pipeline.

You can deploy using either:
- **Option A (Recommended)**: **1-Click AWS CloudFormation** (Deploys all resources automatically in 3 minutes).
- **Option B**: **Manual AWS Management Console Walkthrough** (Step-by-step instructions for AWS Console or AWS Academy Learner Lab).

---

## 2. Prerequisites
1. An active AWS Account or **AWS Academy Learner Lab**.
2. Consistent AWS Region: Use `us-east-1` (N. Virginia) or `ap-south-1` (Mumbai).
3. If using AWS CLI locally:
   ```bash
   aws --version
   aws configure
   ```
   Verify authentication:
   ```bash
   aws sts get-caller-identity
   ```

---

## 3. Option A: Automated CloudFormation Deployment

### 3.1 Deploy via AWS CLI
From the repository root (`Aws-serverless-media-hub`), run:

```bash
# Standard AWS Account (creates custom least-privilege IAM role)
aws cloudformation deploy \
  --template-file infrastructure/cloudformation-template.yaml \
  --stack-name media-hub-infrastructure \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides ProjectPrefix=media-hub Environment=dev UseExistingLabRole=false
```

*(If you are in an **AWS Academy Learner Lab**, change `UseExistingLabRole=true`)*:
```bash
aws cloudformation deploy \
  --template-file infrastructure/cloudformation-template.yaml \
  --stack-name media-hub-infrastructure \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides ProjectPrefix=media-hub Environment=dev UseExistingLabRole=true
```

### 3.2 Deploy via AWS Management Console
1. Open the [AWS CloudFormation Console](https://console.aws.amazon.com/cloudformation).
2. Click **Create stack** -> **With new resources (standard)**.
3. Select **Upload a template file** and choose `infrastructure/cloudformation-template.yaml`.
4. Enter Stack name: `media-hub-infrastructure`.
5. Review parameters:
   - `ProjectPrefix`: `media-hub`
   - `Environment`: `dev`
   - `UseExistingLabRole`: `false` (or `true` if in AWS Academy).
6. Click **Next** -> **Next** -> Check the box **I acknowledge that AWS CloudFormation might create IAM resources** -> Click **Submit**.
7. Wait ~3 minutes until the stack status reaches `CREATE_COMPLETE`.
8. Go to the **Outputs** tab. Note down the values:
   - `InputBucketName`
   - `OutputBucketName`
   - `DynamoDBTableName`
   - `CloudFrontDomainName`
   - `LambdaExecutionRoleArn`

Share these outputs with Person 2 and Person 3 using the template in `infrastructure/interface-contract.md`.

---

## 4. Option B: Manual AWS Console Step-by-Step Guide

If you prefer to create resources manually or need to understand every setting for your project presentation, follow these steps:

### Step 1: Create the Two S3 Buckets
1. Open the **Amazon S3 Console**.
2. **Create Input Bucket**:
   - Click **Create bucket**.
   - Bucket name: `media-hub-input-<YOUR_STUDENT_ID>` (must be globally unique, e.g. `media-hub-input-group07`).
   - Region: Select your chosen region (e.g., `us-east-1`).
   - Keep **Block all public access** checked (**ON**).
   - Encryption: Keep **Amazon S3 managed keys (SSE-S3)**.
   - Click **Create bucket**.
3. **Create Output Bucket**:
   - Click **Create bucket**.
   - Bucket name: `media-hub-output-<YOUR_STUDENT_ID>` (e.g. `media-hub-output-group07`).
   - Keep **Block all public access** checked (**ON**).
   - Encryption: Keep **SSE-S3**.
   - Click **Create bucket**.

### Step 2: Configure CORS on Input Bucket
1. Click on your `media-hub-input-<YOUR_STUDENT_ID>` bucket.
2. Go to the **Permissions** tab.
3. Scroll down to **Cross-origin resource sharing (CORS)** and click **Edit**.
4. Paste the content of `infrastructure/cors-config.json`:
   ```json
   [
     {
       "AllowedHeaders": ["*"],
       "AllowedMethods": ["GET", "PUT", "POST", "HEAD"],
       "AllowedOrigins": ["*"],
       "ExposeHeaders": ["ETag", "x-amz-server-side-encryption", "x-amz-request-id", "x-amz-id-2"],
       "MaxAgeSeconds": 3000
     }
   ]
   ```
5. Click **Save changes**.

### Step 3: Create DynamoDB Table
1. Open the **Amazon DynamoDB Console**.
2. Click **Create table**.
3. Table name: `MediaMetadata`.
4. Partition key: `mediaId` (Type: `String`).
5. Table settings: Select **Customize settings** -> Choose **On-demand** capacity mode.
6. Click **Create table**.

### Step 4: Create IAM Execution Role for Lambda
*(Skip if using AWS Academy `LabRole`)*
1. Open the **IAM Console** -> Click **Roles** -> **Create role**.
2. Trusted entity type: **AWS service** -> Use case: **Lambda**.
3. Click **Next**.
4. Click **Create policy** (opens in a new tab) -> Choose JSON tab and paste:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Sid": "S3InputRead",
         "Effect": "Allow",
         "Action": ["s3:GetObject", "s3:GetObjectVersion"],
         "Resource": "arn:aws:s3:::media-hub-input-*/*"
       },
       {
         "Sid": "S3OutputWrite",
         "Effect": "Allow",
         "Action": ["s3:PutObject", "s3:PutObjectAcl"],
         "Resource": "arn:aws:s3:::media-hub-output-*/*"
       },
       {
         "Sid": "DynamoDBAccess",
         "Effect": "Allow",
         "Action": [
           "dynamodb:PutItem",
           "dynamodb:UpdateItem",
           "dynamodb:GetItem",
           "dynamodb:Scan",
           "dynamodb:Query"
         ],
         "Resource": "arn:aws:dynamodb:*:*:table/MediaMetadata"
       },
       {
         "Sid": "CloudWatchLogs",
         "Effect": "Allow",
         "Action": [
           "logs:CreateLogGroup",
           "logs:CreateLogStream",
           "logs:PutLogEvents"
         ],
         "Resource": "arn:aws:logs:*:*:log-group:/aws/lambda/*"
       }
     ]
   }
   ```
5. Name the policy `MediaPipelineLambdaPolicy` and click **Create policy**.
6. Back on the Create role page, search for and select `MediaPipelineLambdaPolicy`.
7. Role name: `MediaPipelineLambdaRole` -> Click **Create role**.

### Step 5: Configure CloudFront with Origin Access Control (OAC)
1. Open the **Amazon CloudFront Console** -> Click **Create distribution**.
2. **Origin**:
   - Origin domain: Select your `media-hub-output-<YOUR_STUDENT_ID>.s3.amazonaws.com` bucket.
   - Origin access: Choose **Origin access control settings (recommended)**.
   - Click **Create control setting** -> Name: `media-hub-oac` -> Signing protocol: `SigV4` -> Click **Create**.
3. **Default cache behavior**:
   - Viewer protocol policy: **Redirect HTTP to HTTPS**.
   - Allowed HTTP methods: `GET, HEAD, OPTIONS`.
   - Cache key and origin requests: Select **Cache policy and origin request policy (recommended)** -> Cache policy: `CachingOptimized`.
4. Click **Create distribution**.
5. Once created, CloudFront will display a yellow banner prompting: *"The S3 bucket policy needs to be updated"*.
   - Click **Copy policy**.
   - Go to your S3 Output bucket -> **Permissions** tab -> **Bucket policy** -> Click **Edit**.
   - Paste the copied policy (or use `infrastructure/s3-output-oac-policy.json` replacing placeholders) and save.

---

## 5. Wiring the S3 Event Trigger to Lambda (Person 1 + Person 2 Milestone)

Once Person 2 has created the Lambda function (`MediaPipelineProcessor`):
1. Open the **AWS Lambda Console** -> Click on `MediaPipelineProcessor`.
2. Under **Function overview**, click **Add trigger**.
3. Trigger configuration:
   - Source: **S3**.
   - Bucket: Select `media-hub-input-<YOUR_STUDENT_ID>`.
   - Event types: **All object create events** (`s3:ObjectCreated:*`).
   - Prefix: `raw/` *(Recommended: Ensures only uploads in `raw/` invoke the function)*.
   - Recursive invocation acknowledgement: Check the confirmation box acknowledging that recursive loops will not occur.
4. Click **Add**.

---

## 6. End-to-End Pipeline Verification Test (Person 1 Sign-off)

1. **Test Upload to S3 Input**:
   ```bash
   aws s3 cp tests/test_images/sample.jpg s3://media-hub-input-<YOUR_ID>/raw/test-sample.jpg
   ```
2. **Inspect CloudWatch Logs**:
   - Go to CloudWatch -> **Log groups** -> `/aws/lambda/MediaPipelineProcessor`.
   - Verify log stream indicates image resized and saved as WebP.
3. **Verify S3 Output Bucket**:
   ```bash
   aws s3 ls s3://media-hub-output-<YOUR_ID>/processed/
   aws s3 ls s3://media-hub-output-<YOUR_ID>/thumbnails/
   ```
4. **Verify DynamoDB Record**:
   - Open DynamoDB Console -> **Explore items** -> `MediaMetadata`.
   - Verify `status` is `COMPLETED`, `reductionPercent` is populated (~70-85%).
5. **Verify CloudFront Delivery**:
   - Copy the `outputUrl` from DynamoDB (e.g., `https://d123456abcdef.cloudfront.net/processed/test-sample.webp`).
   - Paste it into your browser. The optimized WebP image should render immediately over HTTPS.
6. **Negative Security Test**:
   - Try accessing the S3 output object URL directly:  
     `https://media-hub-output-<YOUR_ID>.s3.amazonaws.com/processed/test-sample.webp`
   - It **MUST** return `403 Access Denied`. This proves the bucket is private and OAC is working.

---

## 7. Troubleshooting Runbook

| Symptom | Root Cause | Fix |
| :--- | :--- | :--- |
| **Frontend upload fails with CORS error** | S3 Input bucket missing CORS configuration | Check Step 2; ensure `PUT` method and `AllowedOrigins: *` are saved in S3 CORS rules. |
| **CloudFront returns 403 Forbidden** | S3 Output Bucket Policy not updated with OAC ARN | Verify S3 Output bucket policy has `cloudfront.amazonaws.com` and matches the CloudFront Distribution ARN. |
| **Lambda not triggering on upload** | S3 Event Notification missing or prefix mismatch | Check if upload key matches the prefix (e.g. `raw/`). Check Lambda resource-based permissions. |
| **Lambda times out after 3 seconds** | Default Lambda timeout (3s) is too low | Increase Lambda timeout to 60s for images, 300s for video in General configuration. |
| **Pillow or FFmpeg import error in Lambda** | Dependencies missing from deployment package | Ensure Lambda layer containing Pillow/FFmpeg is attached to the function. |
