# PowerShell Deployment Automation Script for Person 1 (Infrastructure Lead)
# Usage: .\deploy.ps1 [-ProjectPrefix <string>] [-Region <string>] [-UseLabRole <switch>]

param (
    [string]$ProjectPrefix = "media-hub",
    [string]$Region = "us-east-1",
    [switch]$UseLabRole
)

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " AWS Serverless Media Hub - Infrastructure Deployment" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Verify AWS CLI is installed and authenticated
Write-Host "`n[1/4] Checking AWS CLI authentication..." -ForegroundColor Yellow
$caller = aws sts get-caller-identity --output json 2>$null
if (-not $caller) {
    Write-Host "Error: Unable to authenticate with AWS CLI. Run 'aws configure' first." -ForegroundColor Red
    exit 1
}
$callerObj = $caller | ConvertFrom-Json
Write-Host "Authenticated Account: $($callerObj.Account)" -ForegroundColor Green
Write-Host "Authenticated ARN:     $($callerObj.Arn)" -ForegroundColor Green
Write-Host "Target AWS Region:     $Region" -ForegroundColor Green

# 2. Set Parameters
$StackName = "$ProjectPrefix-infrastructure"
$UseLabRoleParam = if ($UseLabRole) { "true" } else { "false" }

Write-Host "`n[2/4] Deploying CloudFormation Stack: $StackName..." -ForegroundColor Yellow
Write-Host "Using LabRole: $UseLabRoleParam" -ForegroundColor DarkGray

# 3. Execute CloudFormation Deploy
aws cloudformation deploy `
    --template-file "$PSScriptRoot\cloudformation-template.yaml" `
    --stack-name $StackName `
    --region $Region `
    --capabilities CAPABILITY_NAMED_IAM `
    --parameter-overrides ProjectPrefix=$ProjectPrefix Environment=dev UseExistingLabRole=$UseLabRoleParam

if ($LASTEXITCODE -ne 0) {
    Write-Host "`nCloudFormation deployment failed! Review errors above." -ForegroundColor Red
    exit $LASTEXITCODE
}

# 4. Fetch and Display Outputs
Write-Host "`n[3/4] Fetching Stack Outputs..." -ForegroundColor Yellow
$outputs = aws cloudformation describe-stacks `
    --stack-name $StackName `
    --region $Region `
    --query "Stacks[0].Outputs" `
    --output json | ConvertFrom-Json

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host " Deployment Succeeded! Resource Outputs for Team Handover" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green

foreach ($out in $outputs) {
    Write-Host ("{0,-28} : {1}" -f $out.OutputKey, $out.OutputValue) -ForegroundColor White
}

Write-Host "`n[4/4] Next Steps for Person 1:" -ForegroundColor Yellow
Write-Host "1. Share the OutputBucketName, DynamoDBTableName, and CloudFrontDomain with Person 2."
Write-Host "2. Share the InputBucketName and CloudFrontDomain with Person 3."
Write-Host "3. Once Person 2 deploys Lambda, configure the S3 notification trigger."
Write-Host "==========================================================`n" -ForegroundColor Cyan
