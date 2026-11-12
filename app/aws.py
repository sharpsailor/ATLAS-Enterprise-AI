from functools import cache

import boto3
from botocore.config import Config

from app.config import settings


@cache
def s3():
    return boto3.client(
        "s3",
        endpoint_url=settings.aws_endpoint_url or None,
        region_name=settings.aws_default_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def presign_put(key: str, content_type: str, expires: int = 300) -> str:
    return s3().generate_presigned_url(
        "put_object", ExpiresIn=expires,
        Params={"Bucket": settings.s3_bucket, "Key": key, "ContentType": content_type})


def read_object(key: str) -> bytes:
    obj = s3().get_object(Bucket=settings.s3_bucket, Key=key)
    if obj["ContentLength"] > settings.max_upload_bytes:
        raise ValueError(f"file is {obj['ContentLength']} bytes; limit is {settings.max_upload_bytes}")
    return obj["Body"].read()
