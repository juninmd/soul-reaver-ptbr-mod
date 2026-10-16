"""Measure slot fit and transcribe local candidates without granting listening approval."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from audio_pipeline import atomic_json, read_json


def words(text):
    text = unicodedata.normalize('NFKD', text.casefold())
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.findall(r'\w+', text)


def distance(a, b):
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        next_row = [i]
        for j, y in enumerate(b, 1):
            next_row.append(min(next_row[-1] + 1, row[j] + 1, row[j - 1] + (x != y)))
        row = next_row
    return row[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--takes', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--device', choices=['cpu', 'cuda'], default='cuda')
    args = parser.parse_args()
    import torch
    import whisper
    torch.set_num_threads(6)
    model = whisper.load_model(str(args.model.resolve()), device=args.device)
    model_hash = hashlib.sha256(args.model.read_bytes()).hexdigest()
    results = []
    for metadata_path in sorted(args.takes.glob('*/metadata.json')):
        metadata = read_json(metadata_path)
        voice = metadata['identity']['voice']
        audio = metadata_path.parent / 'voice.wav'
        sha = hashlib.sha256(audio.read_bytes()).hexdigest()
        if sha != metadata['audio_sha256']:
            raise ValueError(f'Audio changed: {audio}')
        output = audio.parent / 'asr-pt.json'
        identity = dict(audio_sha256=sha, model_sha256=model_hash, language='pt', temperature=0)
        if output.exists():
            result = read_json(output)
            if result.get('identity') != identity:
                raise ValueError(f'ASR cache identity differs: {output}')
        else:
            result = model.transcribe(str(audio), language='pt', temperature=0, verbose=None)
            result['identity'] = identity
            atomic_json(output, result)
        expected = voice.get('synthesis_text_ptbr', voice['text_ptbr'])
        target = words(expected)
        wer = distance(target, words(result['text'])) / max(1, len(target))
        row = dict(id=voice['id'], speaker=voice['speaker'], audio=str(audio.resolve()),
                   audio_sha256=sha, text_ptbr=voice['text_ptbr'], synthesis_text_ptbr=expected,
                   asr=result['text'].strip(), word_error_rate=wer,
                   duration_seconds=metadata['duration_seconds'], slot_seconds=voice['duration_seconds'],
                   fits_slot=metadata['fits_slot'], needs_text_check=wer > 0.2,
                   human_listening_approved=False)
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    if not results:
        raise ValueError('No completed takes')
    atomic_json(args.takes / 'verification.json', dict(schema=1, voices=results,
                human_listening_approved=False, slot_fit_count=sum(r['fits_slot'] for r in results),
                note='ASR differences, including proper names, require review; this is not a human listening decision.'))


if __name__ == '__main__':
    main()
