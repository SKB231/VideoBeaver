"""
embed_frames.py
---------------
Sample frames from a video at a fixed interval and produce CLIP image
embeddings for each frame. Output is a pickle file with this schema:

    {
        "source": "video",
        "video_path": str,
        "interval_seconds": float,
        "timestamps": np.ndarray, shape (N,)     # seconds from start
        "embeddings": np.ndarray, shape (N, D)   # L2-normalized
        "texts": list[str],                      # empty strings, kept for schema parity
        "model": str,
    }

Usage:
    python embed_frames.py path/to/video.mp4 --interval 2 --output frames.pkl
"""

import argparse
import os
import pickle
import sys
from typing import List

import cv2
import numpy as np
import torch
from PIL import Image
from transformers import CLIPModel, CLIPProcessor


def load_clip(model_name: str, device: str):
    model = CLIPModel.from_pretrained(model_name).to(device)
    model.eval()
    processor = CLIPProcessor.from_pretrained(model_name)
    return model, processor


@torch.no_grad()
def embed_image_batch(model, processor, images: List[Image.Image], device: str) -> np.ndarray:
    """Run CLIP vision encoder on a batch of PIL images, return L2-normalized features."""
    inputs = processor(images=images, return_tensors="pt").to(device)
    features = model.get_image_features(**inputs)
    # Handle case where newer transformers returns BaseModelOutputWithPooling
    if not isinstance(features, torch.Tensor):
        features = features.pooler_output
    features = features / features.norm(dim=-1, keepdim=True)
    return features.cpu().numpy()


def extract_frame_embeddings(
    video_path: str,
    output_path: str,
    interval_seconds: float = 2.0,
    batch_size: int = 16,
    model_name: str = "openai/clip-vit-base-patch32",
):
    if not os.path.exists(video_path):
        raise FileNotFoundError(video_path)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[frames] device={device}  model={model_name}")
    model, processor = load_clip(model_name, device)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps else 0.0
    print(f"[frames] fps={fps:.2f}  total_frames={total_frames}  duration={duration:.1f}s")

    # Step in whole frames; round to nearest to avoid drift on fractional fps.
    step = max(1, int(round(fps * interval_seconds)))

    pending_images: List[Image.Image] = []
    pending_timestamps: List[float] = []
    all_embeddings: List[np.ndarray] = []
    all_timestamps: List[float] = []

    def flush():
        if not pending_images:
            return
        embs = embed_image_batch(model, processor, pending_images, device)
        all_embeddings.append(embs)
        all_timestamps.extend(pending_timestamps)
        pending_images.clear()
        pending_timestamps.clear()

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % step == 0:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pending_images.append(Image.fromarray(frame_rgb))
            pending_timestamps.append(frame_idx / fps)

            if len(pending_images) >= batch_size:
                flush()
                sys.stdout.write(
                    f"\r[frames] embedded {len(all_timestamps)} frames"
                )
                sys.stdout.flush()

        frame_idx += 1

    flush()
    cap.release()
    sys.stdout.write("\n")

    if not all_embeddings:
        raise RuntimeError("No frames were embedded — is the video empty?")

    embeddings = np.concatenate(all_embeddings, axis=0).astype(np.float32)
    timestamps = np.array(all_timestamps, dtype=np.float32)

    data = {
        "source": "video",
        "video_path": os.path.abspath(video_path),
        "interval_seconds": float(interval_seconds),
        "timestamps": timestamps,
        "embeddings": embeddings,
        "texts": [""] * len(timestamps),
        "model": model_name,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as f:
        pickle.dump(data, f)

    print(f"[frames] saved {len(timestamps)} embeddings (dim={embeddings.shape[1]}) -> {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Extract CLIP image embeddings from video frames.")
    parser.add_argument("video_path", help="Path to input video")
    parser.add_argument("--output", "-o", default="frame_embeddings.pkl", help="Output pickle file")
    parser.add_argument("--interval", "-i", type=float, default=2.0, help="Seconds between sampled frames")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--model", default="openai/clip-vit-base-patch32")
    args = parser.parse_args()

    extract_frame_embeddings(
        video_path=args.video_path,
        output_path=args.output,
        interval_seconds=args.interval,
        batch_size=args.batch_size,
        model_name=args.model,
    )


if __name__ == "__main__":
    main()