import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from s3_upload import create_video_upload_presigned_post, UnsupportedFileTypeError
from sqs_publisher import get_publisher
from models import (
    VideoCodec,
    Container,
    CompressRequest,
    CompressResponse,
    VideoMetadata,
)

BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "video-beaver-s3-bucket")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Upload endpoint - get presigned URL for S3 upload
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# Analyze endpoint - trigger ffprobe analysis via SQS
# --------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    s3_key: str
    s3_url: str


class AnalyzeResponse(BaseModel):
    job_id: str
    s3_key: str
    status: str = "queued"


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze_video(body: AnalyzeRequest):
    """Queue a video for ffprobe analysis.

    The frontend calls this immediately after a successful presigned-POST upload.
    Results will be available via the /jobs/{job_id} endpoint or callback.
    """
    try:
        publisher = get_publisher()
        job_id = publisher.publish_probe(
            s3_bucket=BUCKET_NAME,
            s3_key=body.s3_key,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to queue analysis: {e}")

    return AnalyzeResponse(
        job_id=job_id,
        s3_key=body.s3_key,
        status="queued",
    )


# --------------------------------------------------------------------------
# Compress endpoint - trigger ffmpeg compression via SQS
# --------------------------------------------------------------------------

@app.post("/compress", response_model=CompressResponse)
async def compress_video(body: CompressRequest):
    """Queue a video for compression with specified options.

    Options:
    - video_codec: h264, h265, vp9, av1
    - container: mp4, webm, mkv, mov
    - max_bitrate_kbps: Maximum bitrate in kbps (optional)
    - keep_audio: Whether to keep audio track (default: true)
    """
    try:
        publisher = get_publisher()
        job_id = publisher.publish_compress(
            s3_bucket=BUCKET_NAME,
            s3_key=body.s3_key,
            video_codec=body.video_codec,
            container=body.container,
            max_bitrate_kbps=body.max_bitrate_kbps,
            keep_audio=body.keep_audio,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to queue compression: {e}")

    return CompressResponse(
        job_id=job_id,
        status="queued",
        message="Compression job has been queued",
    )


# --------------------------------------------------------------------------
# Callback endpoints - receive results from processing service
# --------------------------------------------------------------------------

class ProbeCallback(BaseModel):
    job_id: str
    s3_key: str
    status: str
    metadata: Optional[VideoMetadata] = None
    error: Optional[str] = None


class CompressCallback(BaseModel):
    job_id: str
    status: str
    output_s3_key: Optional[str] = None
    output_url: Optional[str] = None
    error: Optional[str] = None


# In-memory job store (replace with Redis/DynamoDB in production)
job_results: dict = {}


@app.post("/callbacks/probe")
async def probe_callback(body: ProbeCallback):
    """Receive probe results from the processing service."""
    job_results[body.job_id] = {
        "type": "probe",
        "status": body.status,
        "s3_key": body.s3_key,
        "metadata": body.metadata.model_dump() if body.metadata else None,
        "error": body.error,
    }
    return {"received": True}


@app.post("/callbacks/compress")
async def compress_callback(body: CompressCallback):
    """Receive compression results from the processing service."""
    job_results[body.job_id] = {
        "type": "compress",
        "status": body.status,
        "output_s3_key": body.output_s3_key,
        "output_url": body.output_url,
        "error": body.error,
    }
    return {"received": True}


# --------------------------------------------------------------------------
# Job status endpoint - check job results
# --------------------------------------------------------------------------

@app.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Get the status and results of a processing job."""
    if job_id not in job_results:
        return {
            "job_id": job_id,
            "status": "pending",
            "message": "Job is still processing or not found",
        }

    result = job_results[job_id]
    return {
        "job_id": job_id,
        **result,
    }


# --------------------------------------------------------------------------
# Static files (frontend)
# --------------------------------------------------------------------------

app.mount("/", StaticFiles(directory="static", html=True), name="static")
