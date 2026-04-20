"""
search.py
---------
Load frame and/or subtitle embedding files and run a text similarity
search over them. Because CLIP shares its image/text embedding space and
both files store L2-normalized vectors, ranking is just a single matrix
multiply per source.

Usage:
    python search.py "a person walking a dog on the beach"
    python search.py "someone talks about quantum physics" --frames frames.pkl --subtitles subs.pkl --top-k 5
    python search.py "query" --source audio        # restrict to subtitles
    python search.py "query" --merge               # combine+dedupe nearby hits across sources
"""

import argparse
import os
import pickle
from typing import List, Optional

import numpy as np
import torch
from transformers import CLIPModel, CLIPProcessor


def format_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    if h:
        return f"{h:d}:{m:02d}:{s:05.2f}"
    return f"{m:02d}:{s:05.2f}"


@torch.no_grad()
def encode_query(query: str, model_name: str, device: str) -> np.ndarray:
    model = CLIPModel.from_pretrained(model_name).to(device)
    model.eval()
    processor = CLIPProcessor.from_pretrained(model_name)

    inputs = processor(text=[query], return_tensors="pt", padding=True, truncation=True, max_length=77).to(device)
    features = model.get_text_features(**inputs)
    # Handle case where newer transformers returns BaseModelOutputWithPooling
    if not isinstance(features, torch.Tensor):
        features = features.pooler_output
    features = features / features.norm(dim=-1, keepdim=True)
    return features.cpu().numpy()[0]


def load_pickle(path: str) -> Optional[dict]:
    if not path or not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


def score_file(query_vec: np.ndarray, data: dict) -> List[dict]:
    """Return a list of hit dicts for one embedding file."""
    sims = data["embeddings"] @ query_vec  # (N,) since both are L2-normalized
    hits = []
    for i, sim in enumerate(sims):
        hit = {
            "source": data["source"],
            "timestamp": float(data["timestamps"][i]),
            "similarity": float(sim),
            "text": data["texts"][i] if i < len(data.get("texts", [])) else "",
        }
        if "end_timestamps" in data:
            hit["end_timestamp"] = float(data["end_timestamps"][i])
        hits.append(hit)
    return hits


def merge_nearby(hits: List[dict], window: float = 2.0) -> List[dict]:
    """Optional: if a frame hit and a subtitle hit are within `window` seconds,
    collapse them into one entry, taking the max similarity. Useful when the
    user wants one result per moment rather than two parallel rankings."""
    hits_sorted = sorted(hits, key=lambda h: h["timestamp"])
    merged: List[dict] = []
    for h in hits_sorted:
        if merged and abs(h["timestamp"] - merged[-1]["timestamp"]) <= window:
            prev = merged[-1]
            if h["similarity"] > prev["similarity"]:
                prev["similarity"] = h["similarity"]
            prev["sources"] = sorted(set(prev.get("sources", [prev["source"]]) + [h["source"]]))
            if h.get("text") and not prev.get("text"):
                prev["text"] = h["text"]
        else:
            h = dict(h)
            h["sources"] = [h["source"]]
            merged.append(h)
    return merged


def print_results(query: str, hits: List[dict], top_k: int):
    hits = sorted(hits, key=lambda h: h["similarity"], reverse=True)[:top_k]
    print(f"\nQuery: {query!r}")
    print(f"Top {len(hits)} results:\n")
    print(f"{'#':<4}{'src':<7}{'time':<11}{'score':<8}text")
    print("-" * 78)
    for i, h in enumerate(hits, 1):
        src = ",".join(h["sources"]) if "sources" in h else h["source"]
        text = h.get("text") or "[frame]"
        if len(text) > 55:
            text = text[:52] + "..."
        print(f"{i:<4}{src:<7}{format_time(h['timestamp']):<11}{h['similarity']:<8.4f}{text}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Cosine-similarity search over CLIP video/audio embeddings.")
    parser.add_argument("query", help="Natural-language query")
    parser.add_argument("--frames", default="frames.pkl")
    parser.add_argument("--subtitles", default="subtitle_embeddings.pkl")
    parser.add_argument("--source", choices=["video", "audio", "both"], default="both")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--merge", action="store_true",
                        help="Collapse frame+subtitle hits within 2s into one row")
    parser.add_argument("--model", default="openai/clip-vit-base-patch32",
                        help="Must match the model used at embed time")
    args = parser.parse_args()

    frame_data = load_pickle(args.frames) if args.source in ("video", "both") else None
    sub_data = load_pickle(args.subtitles) if args.source in ("audio", "both") else None

    if not frame_data and not sub_data:
        print("error: no embedding files found. Run embed_frames.py and/or embed_subtitles.py first.")
        raise SystemExit(1)

    # Sanity-check the model matches; mixing dims would silently give garbage.
    for data, label in [(frame_data, args.frames), (sub_data, args.subtitles)]:
        if data and data.get("model") and data["model"] != args.model:
            print(f"warning: {label} was built with {data['model']!r} "
                  f"but --model is {args.model!r}. Scores will be meaningless.")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    query_vec = encode_query(args.query, args.model, device)

    hits: List[dict] = []
    if frame_data:
        hits.extend(score_file(query_vec, frame_data))
    if sub_data:
        hits.extend(score_file(query_vec, sub_data))

    if args.merge:
        hits = merge_nearby(hits, window=2.0)

    print_results(args.query, hits, args.top_k)


if __name__ == "__main__":
    main()