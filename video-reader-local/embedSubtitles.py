"""
embed_subtitles.py
------------------
Transcribe a media file with Whisper, then embed each transcript segment
using CLIP's text encoder so it lives in the same vector space as the
frame embeddings. Output schema:

    {
        "source": "audio",
        "video_path": str,
        "timestamps": np.ndarray, shape (N,)       # segment start, seconds
        "end_timestamps": np.ndarray, shape (N,)   # segment end, seconds
        "embeddings": np.ndarray, shape (N, D)     # L2-normalized
        "texts": list[str],                        # the subtitle text
        "whisper_model": str,
        "model": str,                              # CLIP model (keeps key parity with frames)
    }

NOTE on long segments: CLIP's text encoder has a 77-token context window.
Whisper segments are usually well under that, but we truncate just in case.

Usage:
    python embed_subtitles.py path/to/video.mp4 --whisper-model base --output subs.pkl
"""

import argparse
import os
import pickle
from typing import List

import numpy as np
import torch
import whisper
from transformers import CLIPModel, CLIPProcessor


def load_clip(model_name: str, device: str):
    model = CLIPModel.from_pretrained(model_name).to(device)
    model.eval()
    processor = CLIPProcessor.from_pretrained(model_name)
    return model, processor


@torch.no_grad()
def embed_text_batch(model, processor, texts: List[str], device: str) -> np.ndarray:
    inputs = processor(
        text=texts,
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=77,  # CLIP text encoder context
    ).to(device)
    features = model.get_text_features(**inputs)
    # Handle case where newer transformers returns BaseModelOutputWithPooling
    if not isinstance(features, torch.Tensor):
        features = features.pooler_output
    features = features / features.norm(dim=-1, keepdim=True)
    return features.cpu().numpy()


def extract_subtitle_embeddings(
    video_path: str,
    output_path: str,
    whisper_model_name: str = "base",
    clip_model_name: str = "openai/clip-vit-base-patch32",
    batch_size: int = 32,
):
    if not os.path.exists(video_path):
        raise FileNotFoundError(video_path)

    device = "cuda" if torch.cuda.is_available() else "cpu"

    print(f"[subs] loading whisper: {whisper_model_name}")
    w_model = whisper.load_model(whisper_model_name)

    print(f"[subs] transcribing {video_path}")
    # fp16 only makes sense on CUDA; on CPU it's slower and sometimes broken.
    result = w_model.transcribe(video_path, verbose=False, fp16=(device == "cuda"))
    segments = result.get("segments", [])
    print(f"[subs] {len(segments)} segments from whisper  language={result.get('language')}")

    # Filter empty/whitespace-only segments
    cleaned = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if text:
            cleaned.append({
                "start": float(seg["start"]),
                "end": float(seg["end"]),
                "text": text,
            })

    if not cleaned:
        raise RuntimeError("Whisper returned no non-empty segments.")

    print(f"[subs] loading CLIP: {clip_model_name}")
    model, processor = load_clip(clip_model_name, device)

    all_embeddings: List[np.ndarray] = []
    for i in range(0, len(cleaned), batch_size):
        batch = cleaned[i : i + batch_size]
        embs = embed_text_batch(model, processor, [s["text"] for s in batch], device)
        all_embeddings.append(embs)
        print(f"\r[subs] embedded {min(i + batch_size, len(cleaned))}/{len(cleaned)}", end="", flush=True)
    print()

    embeddings = np.concatenate(all_embeddings, axis=0).astype(np.float32)
    timestamps = np.array([s["start"] for s in cleaned], dtype=np.float32)
    end_timestamps = np.array([s["end"] for s in cleaned], dtype=np.float32)
    texts = [s["text"] for s in cleaned]

    data = {
        "source": "audio",
        "video_path": os.path.abspath(video_path),
        "timestamps": timestamps,
        "end_timestamps": end_timestamps,
        "embeddings": embeddings,
        "texts": texts,
        "whisper_model": whisper_model_name,
        "model": clip_model_name,
        "language": result.get("language"),
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as f:
        pickle.dump(data, f)

    print(f"[subs] saved {len(texts)} embeddings (dim={embeddings.shape[1]}) -> {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Transcribe with Whisper and embed segments with CLIP.")
    parser.add_argument("video_path", help="Path to input video or audio file")
    parser.add_argument("--output", "-o", default="subtitle_embeddings.pkl")
    parser.add_argument(
        "--whisper-model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"],
    )
    parser.add_argument("--clip-model", default="openai/clip-vit-base-patch32")
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()

    extract_subtitle_embeddings(
        video_path=args.video_path,
        output_path=args.output,
        whisper_model_name=args.whisper_model,
        clip_model_name=args.clip_model,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()