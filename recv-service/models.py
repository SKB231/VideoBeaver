"""
models.py — Pydantic models for SQS messages and API requests/responses.
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal
from enum import Enum


# --------------------------------------------------------------------------
# Enums for user-selectable options
# --------------------------------------------------------------------------

class VideoCodec(str, Enum):
    H264 = "h264"
    H265 = "h265"
    VP9 = "vp9"
    AV1 = "av1"


class Container(str, Enum):
    MP4 = "mp4"
    WEBM = "webm"
    MKV = "mkv"
    MOV = "mov"


# --------------------------------------------------------------------------
# Video Metadata (returned by ffprobe)
# --------------------------------------------------------------------------

class VideoStream(BaseModel):
    """Metadata for a single video stream."""
    index: int
    codec_name: str
    codec_long_name: Optional[str] = None
    width: int
    height: int
    duration_seconds: Optional[float] = None
    bit_rate: Optional[int] = None  # bits per second
    frame_rate: Optional[str] = None  # e.g., "30/1" or "29.97"
    pix_fmt: Optional[str] = None


class AudioStream(BaseModel):
    """Metadata for a single audio stream."""
    index: int
    codec_name: str
    codec_long_name: Optional[str] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    bit_rate: Optional[int] = None
    duration_seconds: Optional[float] = None


class VideoMetadata(BaseModel):
    """Complete metadata extracted from ffprobe."""
    filename: str
    format_name: str
    format_long_name: Optional[str] = None
    duration_seconds: float
    size_bytes: int
    bit_rate: int  # overall bitrate in bits per second
    video_streams: list[VideoStream] = []
    audio_streams: list[AudioStream] = []


# --------------------------------------------------------------------------
# SQS Message Types
# --------------------------------------------------------------------------

class ProbeMessage(BaseModel):
    """SQS message payload for video probe requests."""
    message_type: Literal["probe"] = "probe"
    s3_bucket: str
    s3_key: str
    callback_url: Optional[str] = None  # URL to POST results to
    job_id: str  # Unique identifier for this job


class CompressMessage(BaseModel):
    """SQS message payload for video compression requests."""
    message_type: Literal["compress"] = "compress"
    s3_bucket: str
    s3_key: str
    job_id: str

    # User-selected compression options
    video_codec: VideoCodec = VideoCodec.H264
    container: Container = Container.MP4
    max_bitrate_kbps: Optional[int] = None  # Max bitrate in kbps, None = no limit
    keep_audio: bool = True

    # Output location
    output_s3_bucket: Optional[str] = None  # Defaults to input bucket
    output_s3_key: Optional[str] = None  # Defaults to "{original}_compressed.{ext}"

    callback_url: Optional[str] = None


# --------------------------------------------------------------------------
# API Request/Response Models
# --------------------------------------------------------------------------

class AnalyzeResponse(BaseModel):
    """Response from the /analyze endpoint."""
    s3_key: str
    job_id: str
    metadata: VideoMetadata


class CompressRequest(BaseModel):
    """Request body for the /compress endpoint."""
    s3_key: str
    s3_bucket: Optional[str] = None  # Defaults to configured bucket
    video_codec: VideoCodec = VideoCodec.H264
    container: Container = Container.MP4
    max_bitrate_kbps: Optional[int] = None
    keep_audio: bool = True


class CompressResponse(BaseModel):
    """Response from the /compress endpoint."""
    job_id: str
    status: str = "queued"
    message: str = "Compression job has been queued"


class JobStatusResponse(BaseModel):
    """Response for checking job status."""
    job_id: str
    status: Literal["queued", "processing", "completed", "failed"]
    progress_percent: Optional[int] = None
    output_s3_key: Optional[str] = None
    output_s3_url: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Optional[VideoMetadata] = None
