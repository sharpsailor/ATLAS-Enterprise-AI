#!/bin/bash
# Runs inside LocalStack on every start (free plan has no persistence).
set -e
awslocal s3 mb s3://atlas-docs
awslocal sqs create-queue --queue-name atlas-ingest
echo "atlas resources ready"
