"""
Helper utility for Person 1 & Person 3:
Generates a secure, temporary S3 Presigned URL for uploading a file directly
from the browser to the S3 Input Bucket without exposing AWS IAM credentials.
"""

import sys
import uuid
import boto3
from botocore.exceptions import ClientError


def generate_presigned_upload_url(bucket_name: str, original_filename: str, expiration_seconds: int = 300):
    """
    Generate an S3 presigned URL for an HTTP PUT upload.
    """
    s3_client = boto3.client("s3")
    media_id = f"media_{uuid.uuid4().hex[:8]}"
    object_key = f"raw/{media_id}-{original_filename}"

    try:
        presigned_url = s3_client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": bucket_name,
                "Key": object_key,
            },
            ExpiresIn=expiration_seconds,
        )
        return {
            "mediaId": media_id,
            "objectKey": object_key,
            "uploadUrl": presigned_url,
            "expiresInSeconds": expiration_seconds,
        }
    except ClientError as e:
        print(f"Error generating presigned URL: {e}", file=sys.stderr)
        return None


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python generate_presigned_url.py <INPUT_BUCKET_NAME> <FILENAME>")
        print("Example: python generate_presigned_url.py media-hub-input-group07 sample.jpg")
        sys.exit(1)

    bucket = sys.argv[1]
    filename = sys.argv[2]
    result = generate_presigned_upload_url(bucket, filename)

    if result:
        print("\n--- Presigned Upload URL Generated Successfully ---")
        print(f"Media ID:    {result['mediaId']}")
        print(f"Object Key:  {result['objectKey']}")
        print(f"Expires In:  {result['expiresInSeconds']} seconds")
        print(f"\nUpload URL (Use HTTP PUT):\n{result['uploadUrl']}")
        print("\nTest with curl:")
        print(f'curl -X PUT -T "{filename}" "{result["uploadUrl"]}"\n')
