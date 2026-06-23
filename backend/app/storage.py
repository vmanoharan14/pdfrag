import asyncio
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import Settings, get_settings


class ObjectStorage:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.minio_bucket
        self.client: BaseClient = boto3.client(
            "s3",
            endpoint_url=settings.minio_url,
            aws_access_key_id=settings.minio_root_user,
            aws_secret_access_key=settings.minio_root_password,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )

    async def ensure_bucket(self) -> None:
        def ensure() -> None:
            try:
                self.client.head_bucket(Bucket=self.bucket)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code not in {"404", "NoSuchBucket"}:
                    raise
                self.client.create_bucket(Bucket=self.bucket)

        await asyncio.to_thread(ensure)

    async def upload(
        self,
        file: BinaryIO,
        object_key: str,
        content_type: str,
    ) -> None:
        await self.ensure_bucket()
        await asyncio.to_thread(
            self.client.upload_fileobj,
            file,
            self.bucket,
            object_key,
            ExtraArgs={"ContentType": content_type},
        )

    async def delete(self, object_key: str) -> None:
        await asyncio.to_thread(
            self.client.delete_object,
            Bucket=self.bucket,
            Key=object_key,
        )

    async def download_to_path(self, object_key: str, destination: Path) -> None:
        await asyncio.to_thread(
            self.client.download_file,
            self.bucket,
            object_key,
            str(destination),
        )

    async def upload_bytes(
        self,
        payload: bytes,
        object_key: str,
        content_type: str,
    ) -> None:
        with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as buffered:
            buffered.write(payload)
            buffered.seek(0)
            await self.upload(buffered, object_key, content_type)


@lru_cache
def get_object_storage() -> ObjectStorage:
    return ObjectStorage(get_settings())
