"""Build legacy ASCII captions or a separate UTF-8 NFC Unicode-v1 candidate.

The default legacy format intentionally strips Portuguese accents and maps select
punctuation to ASCII because the current native renderer rejects UTF-8 bytes.
Unicode-v1 is JSON rather than TSV so the existing line parser rejects it. It is a data contract only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import unicodedata
import wave

from audio_pipeline import atomic_json, read_json, validate_voice_namespace


UNICODE_PAGE_LIMIT = 220


def paginate(text, duration_ms, max_chars=UNICODE_PAGE_LIMIT):
    """Split by words and allocate contiguous integer-ms intervals by character weight."""
    words = text.split()
    if not words or any(len(word) > max_chars for word in words):
        raise ValueError('Caption contains a word too long to paginate')
    chunks = []
    current = ""
    for word in words:
        candidate = word if not current else current + " " + word
        if len(candidate) > max_chars:
            chunks.append(current)
            current = word
        else:
            current = candidate
    chunks.append(current)
    if duration_ms < len(chunks):
        raise ValueError('Caption duration is too short for one millisecond per page')
    total_weight = sum(len(chunk) for chunk in chunks)
    pages = []
    elapsed_weight = 0
    start_ms = 0
    for position, chunk in enumerate(chunks):
        elapsed_weight += len(chunk)
        end_ms = duration_ms if position == len(chunks) - 1 else duration_ms * elapsed_weight // total_weight
        if end_ms - start_ms < 1:
            raise ValueError('Caption duration cannot provide one millisecond per page')
        pages.append(dict(text=chunk, start_ms=start_ms, end_ms=end_ms))
        start_ms = end_ms
    return pages


def build(plan_path, output, review_candidate=False, format="legacy"):
    if format not in {"legacy", "unicode-v1"}:
        raise ValueError("Unsupported subtitle format")
    # The installed proxy consumes an ASCII TSV. A Unicode-v1 envelope is JSON;
    # allowing it to be named subtitles.tsv makes it look deployable even though
    # runtime.cpp deliberately rejects its first non-ASCII byte (or JSON syntax).
    if format == "unicode-v1" and Path(output).suffix.lower() != ".json":
        raise ValueError("unicode-v1 captions are JSON; use a .json output, never the runtime .tsv path")
    if output.exists() or output.with_suffix('.evidence.json').exists():
        raise ValueError('Choose a fresh subtitle output path')
    plan = read_json(plan_path)
    validate_voice_namespace(plan)
    lines = []
    evidence = []
    seen = set()
    for voice in plan['voices']:
        index = voice['id']
        if type(index) is not int or not 0 <= index < 479 or index in seen:
            raise ValueError('Invalid or duplicate caption id')
        seen.add(index)
        if voice.get('approved_text') is not True or (not review_candidate and voice.get('approved_audio') is not True):
            raise ValueError('Unapproved voice requires explicit review-candidate mode')
        audio = (plan_path.parent / voice['audio']).resolve()
        sha = hashlib.sha256(audio.read_bytes()).hexdigest()
        if sha != voice['audio_sha256']:
            raise ValueError(f'Caption audio changed: {audio}')
        with wave.open(str(audio)) as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 22050):
                raise ValueError('Caption audio format differs from game format')
            seconds = wav.getnframes() / wav.getframerate()
        if seconds + voice.get('lead_samples', 0) / 22050 > voice['duration_seconds']:
            raise ValueError(f'Voice {index} does not fit its slot')
        milliseconds = round(1000 * seconds)
        if not 1 <= milliseconds <= 60000 or (format == 'legacy' and milliseconds < 100):
            raise ValueError('Caption duration outside native runtime limits')
        raw_text = voice['text_ptbr']
        if not isinstance(raw_text, str):
            raise ValueError(f'Voice {index} caption must be text')
        if format == 'unicode-v1':
            if any(unicodedata.category(char) in {'Cc', 'Cf', 'Cs', 'Cn', 'Co'} for char in raw_text):
                raise ValueError(f'Voice {index} has unsupported caption characters')
            canonical = unicodedata.normalize('NFC', raw_text.strip())
        else:
            canonical = raw_text.strip()
        if format == 'legacy':
            text = unicodedata.normalize('NFKD', canonical)
            text = ''.join(c for c in text if not unicodedata.combining(c))
            text = text.replace('—', '-').replace('–', '-').replace('…', '...')
            text = text.replace('“', '"').replace('”', '"').replace('’', "'")
            if not text or len(text) > 4000 or any(ord(c) < 32 or ord(c) > 126 or c == '@' for c in text):
                raise ValueError(f'Voice {index} has unsupported caption characters')
        else:
            text = canonical
            if not text or len(text) > 4000:
                raise ValueError(f'Voice {index} has unsupported caption characters')
            # NFC is applied above. Reject categories unsupported by the target font
            # contract even if a future normalization step would remove them.
        if any(len(word) > 60 for word in re.findall(r'\S+', text)):
            raise ValueError('Caption word exceeds native layout limit')
        lines.append((index, f'{index}\t{milliseconds}\t{text}\n'))
        evidence.append(dict(id=index, text_ptbr=canonical, audio_sha256=sha,
                             duration_ms=milliseconds, human_listening_approved=voice.get('approved_audio') is True))
    if not lines:
        raise ValueError('Empty caption plan')
    if format == 'unicode-v1':
        rows = []
        for line_id, line in sorted(lines):
            _, duration, text = line.rstrip('\n').split('\t', 2)
            duration_ms = int(duration)
            rows.append(dict(id=line_id, duration_ms=duration_ms, text=text,
                             pages=paginate(text, duration_ms)))
        envelope = dict(schema=1, format='unicode-v1', encoding='UTF-8', normalization='NFC',
                        namespace='voices.dat', captions=rows)
        payload = (json.dumps(envelope, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
    else:
        payload = ''.join(line for _, line in sorted(lines)).encode('ascii')
    if len(payload) > 256 * 1024:
        raise ValueError('Caption table exceeds native runtime limit')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        stream.write(payload)
    metadata = dict(schema=1, format=format, encoding='UTF-8' if format == 'unicode-v1' else 'ASCII',
        normalization='NFC' if format == 'unicode-v1' else 'legacy accent-stripping',
        namespace='voices.dat', origin=str(plan_path.resolve()), source_sha256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        sha256=hashlib.sha256(payload).hexdigest(), captions=evidence,
        review_candidate=review_candidate, note='Unicode page breaks and character-weighted timings are deterministic heuristics; every page still requires host GDI layout validation and runtime synchronization review.')
    atomic_json(output.with_suffix('.evidence.json'), metadata)
    return dict(captions=len(lines), output=str(output), sha256=hashlib.sha256(payload).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--review-candidate', action='store_true')
    parser.add_argument('--format', choices=('legacy', 'unicode-v1'), default='legacy',
                        help='legacy strips accents for the ASCII runtime; unicode-v1 is a separate, currently unconsumed candidate format')
    args = parser.parse_args()
    print(json.dumps(build(args.plan, args.output, args.review_candidate, args.format)))
