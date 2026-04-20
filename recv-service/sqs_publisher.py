"""
sqs_publisher.py — Publish messages to SQS for video processing.
"""

import boto3
import json
import logging
import os
import uuid
from typing import Optional

from models import ProbeMessage, CompressMessage, VideoCodec, Container

logger = logging.getLogger(__name__)

# Separate queues for different job types to avoid HOL blocking
# Probe jobs are fast (seconds), compress jobs are slow (minutes)
SQS_PROBE_QUEUE_URL = os.getenv("SQS_PROBE_QUEUE_URL", "")
SQS_COMPRESS_QUEUE_URL = os.getenv("SQS_COMPRESS_QUEUE_URL", "")


class SQSPublisher:
    """Publishes video processing messages to SQS."""

    def __init__(self, probe_queue_url: str = None, compress_queue_url: str = None):
        self.probe_queue_url = probe_queue_url or SQS_PROBE_QUEUE_URL
        self.compress_queue_url = compress_queue_url or SQS_COMPRESS_QUEUE_URL
        self.sqs = boto3.client("sqs")

    def publish_probe(
        self,
        s3_bucket: str,
        s3_key: str,
        callback_url: Optional[str] = None,
    ) -> str:
        """Publish a video probe request to SQS.

        :param s3_bucket: S3 bucket containing the video.
        :param s3_key: S3 object key of the video.
        :param callback_url: Optional URL to POST results to.
        :return: The job ID for tracking.
        """
        job_id = str(uuid.uuid4())

        message = ProbeMessage(
            message_type="probe",
            job_id=job_id,
            s3_bucket=s3_bucket,
            s3_key=s3_key,
            callback_url=callback_url,
        )

        self._send_message(self.probe_queue_url, message.model_dump())
        logger.info("Published probe job %s for s3://%s/%s", job_id, s3_bucket, s3_key)

        return job_id

    def publish_compress(
        self,
        s3_bucket: str,
        s3_key: str,
        video_codec: VideoCodec = VideoCodec.H264,
        container: Container = Container.MP4,
        max_bitrate_kbps: Optional[int] = None,
        keep_audio: bool = True,
        callback_url: Optional[str] = None,
    ) -> str:
        """Publish a video compression request to SQS.

        :param s3_bucket: S3 bucket containing the video.
        :param s3_key: S3 object key of the video.
        :param video_codec: Target video codec.
        :param container: Target container format.
        :param max_bitrate_kbps: Maximum bitrate in kbps (None = no limit).
        :param keep_audio: Whether to keep the audio track.
        :param callback_url: Optional URL to POST results to.
        :return: The job ID for tracking.
        """
        job_id = str(uuid.uuid4())

        message = CompressMessage(
            message_type="compress",
            job_id=job_id,
            s3_bucket=s3_bucket,
            s3_key=s3_key,
            video_codec=video_codec,
            container=container,
            max_bitrate_kbps=max_bitrate_kbps,
            keep_audio=keep_audio,
            callback_url=callback_url,
        )

        self._send_message(self.compress_queue_url, message.model_dump())
        logger.info(
            "Published compress job %s for s3://%s/%s (codec=%s, container=%s)",
            job_id, s3_bucket, s3_key, video_codec, container
        )

        return job_id

    def _send_message(self, queue_url: str, message_body: dict) -> None:
        """Send a message to the specified SQS queue."""
        if not queue_url:
            raise ValueError("Queue URL is not configured")

        self.sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(message_body),
        )


# Global publisher instance
_publisher: Optional[SQSPublisher] = None


def get_publisher() -> SQSPublisher:
    """Get or create the global SQS publisher."""
    global _publisher
    if _publisher is None:
        _publisher = SQSPublisher()
    return _publisher
