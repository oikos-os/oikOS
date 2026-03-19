"""File upload endpoint — accepts multipart, returns file content for chat context."""

from __future__ import annotations

from fastapi import APIRouter, UploadFile, File

router = APIRouter()

MAX_FILE_SIZE = 1024 * 1024  # 1MB per file
ALLOWED_EXTENSIONS = {".txt", ".md", ".py", ".js", ".ts", ".tsx", ".json", ".yaml", ".yml", ".toml", ".csv", ".log"}


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if file.filename:
        ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext and ext not in ALLOWED_EXTENSIONS:
            return {"error": f"File type {ext} not allowed", "allowed": list(ALLOWED_EXTENSIONS)}

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        return {"error": f"File too large (max {MAX_FILE_SIZE // 1024}KB)"}

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return {"error": "File is not valid UTF-8 text"}

    return {
        "name": file.filename,
        "size": len(content),
        "content": text,
    }
