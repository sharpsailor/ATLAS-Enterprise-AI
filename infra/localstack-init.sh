#!/bin/bash
# Runs inside LocalStack on every start (free plan has no persistence).
set -e
awslocal s3 mb s3://atlas-docs
awslocal sqs create-queue --queue-name atlas-ingest
# Browser uploads PUT straight to S3 via presigned URLs, so the bucket needs CORS.
awslocal s3api put-bucket-cors --bucket atlas-docs --cors-configuration '{"CORSRules":[{"AllowedHeaders":["*"],"AllowedMethods":["PUT"],"AllowedOrigins":["http://127.0.0.1:8000","http://localhost:8000"],"ExposeHeaders":["ETag"],"MaxAgeSeconds":3000}]}'
echo "atlas resources ready"
