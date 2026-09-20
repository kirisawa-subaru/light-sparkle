"""Optional S3-compatible upload (AWS S3, Cloudflare R2, Tencent COS, Aliyun
OSS, MinIO, ...). Needs `pip install "telepaste[s3]"` for boto3."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .config import ConfigError, S3Config


class UploadError(RuntimeError):
    pass


def _reason(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if code:
            return str(code)
    return type(exc).__name__


class Uploader:
    def __init__(self, config: S3Config, client: Any | None = None):
        self.config = config
        if client is None:
            try:
                import boto3
            except ImportError:
                raise ConfigError(
                    "S3 upload needs boto3: pip install 'telepaste[s3]'") from None
            client = boto3.client(
                "s3",
                endpoint_url=config.endpoint_url,
                region_name=config.region,
                aws_access_key_id=config.access_key_id,
                aws_secret_access_key=config.secret_access_key,
            )
        self.client = client

    def describe(self) -> str:
        where = self.config.endpoint_url or "aws"
        links = ("public" if self.config.public_base_url
                 else f"presigned, {self.config.url_expire}s")
        return f"s3://{self.config.bucket} via {where} · links {links}"

    def key_for(self, day: str, filename: str) -> str:
        return "/".join(part for part in (self.config.prefix, day, filename) if part)

    def url_for(self, key: str) -> str:
        if self.config.public_base_url:
            return f"{self.config.public_base_url}/{quote(key, safe='/')}"
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.config.bucket, "Key": key},
                ExpiresIn=self.config.url_expire,
            )
        except Exception as exc:
            raise UploadError(f"presign failed for {key}: {_reason(exc)}") from exc

    def upload(self, data: bytes, key: str, content_type: str) -> str:
        """Blocking; the bot calls this through asyncio.to_thread."""
        try:
            self.client.put_object(
                Bucket=self.config.bucket, Key=key, Body=data, ContentType=content_type)
        except Exception as exc:
            raise UploadError(f"upload failed for {key}: {_reason(exc)}") from exc
        return self.url_for(key)
