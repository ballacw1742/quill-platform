"""Blob storage tool — reads files from local paths, GCS, or MinIO."""
from __future__ import annotations

from google.adk.tools import FunctionTool


def read_blob_file(path: str, encoding: str = "utf-8") -> str:
    """Read a file from local disk, GCS (gs://), or MinIO (s3://) and return its text content.

    TODO: wire to GCS / MinIO for remote URIs.
      - Local: stdlib open()
      - GCS: google-cloud-storage client
      - MinIO/S3: boto3 or minio-py

    Args:
        path: Local file path or URI
            (e.g. "/data/submittals/spec.pdf", "gs://bucket/key", "s3://bucket/key").
        encoding: Text encoding for decoding bytes (default "utf-8").

    Returns:
        String contents of the file (plain text or base64 for binary files).
        Returns a stub warning string if the path is not a real local file.
    """
    import os

    if path.startswith("gs://") or path.startswith("s3://"):
        # TODO: implement remote blob read
        return (
            f"[STUB] read_blob_file: remote URI {path!r} — "
            "TODO: wire to GCS/MinIO client."
        )

    if os.path.isfile(path):
        with open(path, encoding=encoding, errors="replace") as f:
            return f.read()

    return (
        f"[STUB] read_blob_file: path {path!r} not found on local disk. "
        "TODO: confirm storage backend."
    )


read_blob_file_tool = FunctionTool(func=read_blob_file)
