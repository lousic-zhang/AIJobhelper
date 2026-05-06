from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile


@dataclass
class StoredFile:
    file_name: str
    file_path: str


class FileStorageService:
    def __init__(self, upload_dir: Path) -> None:
        self.upload_dir = upload_dir
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    async def save_resume(self, upload_file: UploadFile) -> StoredFile:
        suffix = Path(upload_file.filename or "").suffix.lower()
        if suffix != ".pdf":
            raise HTTPException(status_code=400, detail="第一阶段仅支持 PDF 简历上传")

        target_name = f"{uuid4().hex}{suffix}"
        target_path = self.upload_dir / target_name
        content = await upload_file.read()
        if not content:
            raise HTTPException(status_code=400, detail="上传文件为空")
        target_path.write_bytes(content)
        return StoredFile(file_name=upload_file.filename or target_name, file_path=str(target_path))

