#!/usr/bin/env python3
"""Baixa/retoma os pesos do checkpoint TTS local (Qwen3-TTS) para um diretório.

Só baixa `model.safetensors`; os demais arquivos (config, tokenizer, speech_tokenizer)
já costumam estar presentes. Retoma download interrompido.
"""
from __future__ import annotations

import argparse
import sys

from huggingface_hub import hf_hub_download


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="Qwen/Qwen3-TTS-12Hz-1.7B-Base")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--model", required=True, help="diretório local do checkpoint")
    parser.add_argument("--filename", default="model.safetensors")
    args = parser.parse_args()

    path = hf_hub_download(
        repo_id=args.repo,
        filename=args.filename,
        revision=args.revision,
        local_dir=args.model,
    )
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
