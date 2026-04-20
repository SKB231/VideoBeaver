"""
video_probe.py — ffprobe analysis for uploaded videos.

Workflow:
  1. Download the video from S3 to a temporary file.
  2. Run ffprobe to extract stream/format metadata.
  3. Parse the JSON output and return a structured VideoMetadata object.
"""

import boto3
import json
import logging
import subprocess
import tempfile
import os
from typing import Optional

from models import VideoMetadata, VideoStream, AudioStream

logger = logging.getLogger(__name__)

# ffprobe command template
FFPROBE_CMD = [
    "ffprobe",
    "-v", "quiet",
    "-print_format", "json",
    "-show_format",
    "-show_streams",
]


def download_from_s3(bucket: str, key: str, local_path: str) -> None:
    """Download a file from S3 to a local path."""
    s3 = boto3.client("s3")
    s3.download_file(bucket, key, local_path)
    logger.info("Downloaded s3://%s/%s to %s", bucket, key, local_path)


def run_ffprobe(file_path: str) -> dict:
    """Run ffprobe on a local file and return parsed JSON output.
    
    :param file_path: Path to the video file.
    :return: Parsed ffprobe JSON output.
    :raises RuntimeError: If ffprobe fails or returns invalid output.
    """
    cmd = FFPROBE_CMD + [file_path]
    
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse ffprobe output: {e}")


def parse_ffprobe_output(ffprobe_data: dict, filename: str) -> VideoMetadata:
    """Parse ffprobe JSON output into a VideoMetadata model.
    
    :param ffprobe_data: Raw ffprobe JSON output.
    :param filename: Original filename for reference.
    :return: Structured VideoMetadata object.
    """
    format_info = ffprobe_data.get("format", {})
    streams = ffprobe_data.get("streams", [])
    
    video_streams = []
    audio_streams = []
    
    for stream in streams:
        codec_type = stream.get("codec_type")
        
        if codec_type == "video":
            # Parse frame rate from avg_frame_rate or r_frame_rate
            frame_rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate")
            
            video_streams.append(VideoStream(
                index=stream.get("index", 0),
                codec_name=stream.get("codec_name", "unknown"),
                codec_long_name=stream.get("codec_long_name"),
                width=stream.get("width", 0),
                height=stream.get("height", 0),
                duration_seconds=_parse_float(stream.get("duration")),
                bit_rate=_parse_int(stream.get("bit_rate")),
                frame_rate=frame_rate,
                pix_fmt=stream.get("pix_fmt"),
            ))
        
        elif codec_type == "audio":
            audio_streams.append(AudioStream(
                index=stream.get("index", 0),
                codec_name=stream.get("codec_name", "unknown"),
                codec_long_name=stream.get("codec_long_name"),
                sample_rate=_parse_int(stream.get("sample_rate")),
                channels=stream.get("channels"),
                bit_rate=_parse_int(stream.get("bit_rate")),
                duration_seconds=_parse_float(stream.get("duration")),
            ))
    
    return VideoMetadata(
        filename=filename,
        format_name=format_info.get("format_name", "unknown"),
        format_long_name=format_info.get("format_long_name"),
        duration_seconds=_parse_float(format_info.get("duration")) or 0.0,
        size_bytes=_parse_int(format_info.get("size")) or 0,
        bit_rate=_parse_int(format_info.get("bit_rate")) or 0,
        video_streams=video_streams,
        audio_streams=audio_streams,
    )


def _parse_float(value) -> Optional[float]:
    """Safely parse a value to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _parse_int(value) -> Optional[int]:
    """Safely parse a value to int."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def probe_video(s3_key: str, s3_url: str, bucket: str = None) -> dict:
    """Run ffprobe on a video that was just uploaded to S3.

    Downloads the full video to a temp file, runs ffprobe, and returns metadata.

    :param s3_key: S3 object key (e.g. "myvideo.mp4")
    :param s3_url: The presigned POST bucket URL used for the upload.
    :param bucket: S3 bucket name. If None, extracted from s3_url.
    :return: Dict of ffprobe metadata (format + streams).
    :raises RuntimeError: If the download or ffprobe invocation fails.
    """
    logger.info("probe_video called: key=%s url=%s", s3_key, s3_url)
    
    # Extract bucket from URL if not provided
    if bucket is None:
        # URL format: https://{bucket}.s3.{region}.amazonaws.com or https://s3.{region}.amazonaws.com/{bucket}
        bucket = _extract_bucket_from_url(s3_url)
    
    # Determine file extension for temp file
    _, ext = os.path.splitext(s3_key)
    
    # Download to temp file and run ffprobe
    with tempfile.NamedTemporaryFile(suffix=ext, delete=True) as tmp_file:
        download_from_s3(bucket, s3_key, tmp_file.name)
        ffprobe_data = run_ffprobe(tmp_file.name)
    
    # Parse and return metadata
    metadata = parse_ffprobe_output(ffprobe_data, s3_key)
    
    logger.info("probe_video complete: key=%s metadata=%s", s3_key, metadata.model_dump())
    return metadata.model_dump()


def probe_video_from_message(bucket: str, s3_key: str) -> VideoMetadata:
    """Run ffprobe on a video specified by bucket and key.
    
    This is the main entry point for SQS message processing.
    
    :param bucket: S3 bucket name.
    :param s3_key: S3 object key.
    :return: VideoMetadata object with parsed ffprobe data.
    """
    logger.info("probe_video_from_message: bucket=%s key=%s", bucket, s3_key)
    
    _, ext = os.path.splitext(s3_key)
    
    with tempfile.NamedTemporaryFile(suffix=ext, delete=True) as tmp_file:
        download_from_s3(bucket, s3_key, tmp_file.name)
        ffprobe_data = run_ffprobe(tmp_file.name)
    
    return parse_ffprobe_output(ffprobe_data, s3_key)


def _extract_bucket_from_url(s3_url: str) -> str:
    """Extract bucket name from S3 URL.
    
    Handles both path-style and virtual-hosted-style URLs.
    """
    from urllib.parse import urlparse
    
    parsed = urlparse(s3_url)
    host = parsed.hostname or ""
    
    # Virtual-hosted-style: {bucket}.s3.{region}.amazonaws.com
    if ".s3." in host and host.endswith(".amazonaws.com"):
        return host.split(".s3.")[0]
    
    # Path-style: s3.{region}.amazonaws.com/{bucket}
    if host.startswith("s3.") and host.endswith(".amazonaws.com"):
        path_parts = parsed.path.strip("/").split("/")
        if path_parts:
            return path_parts[0]
    
    raise ValueError(f"Could not extract bucket from URL: {s3_url}")
