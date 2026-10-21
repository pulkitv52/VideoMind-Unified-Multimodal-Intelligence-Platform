"""Privileged, one-shot storage setup. Root credentials never enter the API."""

import json
import os
import time

from minio import Minio
from minio.credentials import StaticProvider
from minio.minioadmin import MinioAdmin


def main():
    endpoint = os.environ["VM_MINIO_ENDPOINT"]
    root = os.environ["VM_MINIO_ROOT_USER"]
    secret = os.environ["VM_MINIO_ROOT_PASSWORD"]
    client = Minio(endpoint, access_key=root, secret_key=secret, secure=False)
    for attempt in range(30):
        try:
            client.list_buckets()
            break
        except Exception:
            if attempt == 29:
                raise RuntimeError("Storage initialization unavailable") from None
            time.sleep(1)
    bucket = os.environ.get("VM_MINIO_BUCKET", "videomind")
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    # No anonymous policy exists on the private bucket.
    admin = MinioAdmin(
        endpoint=endpoint, credentials=StaticProvider(root, secret), secure=False
    )
    admin.user_add(os.environ["VM_MINIO_ACCESS_KEY"], os.environ["VM_MINIO_SECRET_KEY"])
    admin.policy_add(
        "videomind-bucket",
        policy={
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["s3:GetBucketLocation", "s3:ListBucket"],
                    "Resource": [f"arn:aws:s3:::{bucket}"],
                },
                {
                    "Effect": "Allow",
                    "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                    "Resource": [f"arn:aws:s3:::{bucket}/*"],
                },
            ],
        },
    )
    policies = (
        json.loads(admin.user_info(os.environ["VM_MINIO_ACCESS_KEY"]))
        .get("policyName", "")
        .split(",")
    )
    if "videomind-bucket" not in policies:
        admin.attach_policy(
            ["videomind-bucket"], user=os.environ["VM_MINIO_ACCESS_KEY"]
        )
    print("Private storage initialized")


if __name__ == "__main__":
    main()
