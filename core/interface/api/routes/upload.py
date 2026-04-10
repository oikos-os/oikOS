"""File upload endpoint — accepts multipart, returns file content for chat context."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File

router = APIRouter()

MAX_FILE_SIZE = 1024 * 1024  # 1MB per file
ALLOWED_EXTENSIONS = {".txt", ".md", ".py", ".js", ".ts", ".tsx", ".json", ".yaml", ".yml", ".toml", ".csv", ".log"}


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename or "." not in file.filename:
        raise HTTPException(400, "Filename with extension required")
    ext = "." + file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"File type {ext} not allowed")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, f"File too large (max {MAX_FILE_SIZE // 1024}KB)")

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "File is not valid UTF-8 text")

    return {
        "name": file.filename,
        "size": len(content),
        "content": text,
    }
