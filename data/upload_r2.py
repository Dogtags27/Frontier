"""Upload staging PDFs to R2. Skips an object that already has the same size."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import boto3
from botocore.exceptions import ClientError

from r2_config import INDEX, ROOT, load_env, r2_key, write_index

PDF_DIR = ROOT / "data" / "pdfs"


def client(env):
    return boto3.client(
        "s3",
        endpoint_url=env["R2_ENDPOINT"],
        aws_access_key_id=env["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=env["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def already_there(s3, bucket, key, size):
    try:
        head = s3.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise
    return head.get("ContentLength") == size


def main():
    env = load_env()
    n = write_index(env)
    print(f"index {n} -> {INDEX}", flush=True)
    s3 = client(env)
    bucket = env["R2_BUCKET"]
    s3.head_bucket(Bucket=bucket)
    rows = [json.loads(line) for line in INDEX.read_text(encoding="utf-8").splitlines()]
    uploaded = skipped = 0
    for i, row in enumerate(rows, 1):
        path = PDF_DIR / f"{row['arxiv_id']}.pdf"
        size = path.stat().st_size
        key = r2_key(row["arxiv_id"])
        if already_there(s3, bucket, key, size):
            skipped += 1
        else:
            s3.upload_file(
                str(path),
                bucket,
                key,
                ExtraArgs={"ContentType": "application/pdf"},
            )
            uploaded += 1
        if i % 25 == 0 or i == len(rows):
            print(f"r2 {i}/{len(rows)} uploaded {uploaded} skipped {skipped}", flush=True)
    print(f"done uploaded {uploaded} skipped {skipped}", flush=True)


if __name__ == "__main__":
    main()
