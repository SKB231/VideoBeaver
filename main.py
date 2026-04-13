from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from s3_upload import create_video_upload_presigned_post, UnsupportedFileTypeError
from typing import Annotated

BUCKET_NAME = "video-beaver-s3-bucket"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class UploadRequest(BaseModel):
    filename: str
    file_size: int


@app.post("/upload")
async def upload_file(body: UploadRequest):
    try:
        presigned = create_video_upload_presigned_post(BUCKET_NAME, body.filename)
    except UnsupportedFileTypeError as e:
        raise HTTPException(status_code=415, detail=str(e))

    return {"url": presigned["url"], "fields": presigned["fields"]}



@app.get("/items/{item_id}")
def read_item(item_id: int, q: str | None = None):
    return {"item_id": item_id, "q": q}

app.mount("/", StaticFiles(directory="static", html=True), name="static")