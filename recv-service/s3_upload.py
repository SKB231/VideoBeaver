import boto3
from botocore.exceptions import ClientError
import logging

ALLOWED_VIDEO_TYPES = {
    '.mp4': 'video/mp4',
    '.webm': 'video/webm',
    '.mov': 'video/quicktime',
    '.avi': 'video/x-msvideo',
    '.mkv': 'video/x-matroska',
    '.m4v': 'video/x-m4v',
}


class UnsupportedFileTypeError(ValueError):
    pass


def create_video_upload_presigned_post(bucket_name: str, object_name: str, expiration: int = 3600):
    """Generate a presigned S3 POST URL for uploading a video file.

    Validates the file extension against allowed video types before generating the URL.

    :param bucket_name: S3 bucket name
    :param object_name: S3 object key (must include file extension)
    :param expiration: Seconds until the presigned URL expires (default 1 hour)
    :return: Dict with 'url' and 'fields' keys for the multipart POST
    :raises UnsupportedFileTypeError: If the file extension is not an allowed video type
    :raises ClientError: If the presigned URL could not be generated
    """
    ext = '.' + object_name.rsplit('.', 1)[-1].lower() if '.' in object_name else ''
    content_type = ALLOWED_VIDEO_TYPES.get(ext)
    if content_type is None:
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{ext}'. Allowed types: {list(ALLOWED_VIDEO_TYPES.keys())}"
        )

    s3_client = boto3.client('s3')
    try:
        response = s3_client.generate_presigned_post(
            bucket_name,
            object_name,
            Fields={'Content-Type': content_type},
            Conditions=[{'Content-Type': content_type}],
            ExpiresIn=expiration,
        )
    except ClientError as e:
        logging.error(e)
        raise

    return response
