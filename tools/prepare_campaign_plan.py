"""Pin local source audio and accepted voice profiles for a translated campaign batch."""
import argparse
import hashlib
import json
from pathlib import Path
import wave

from audio_pipeline import atomic_json, read_json, validate_voice_namespace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--translations', type=Path, required=True)
    parser.add_argument('--catalogue', type=Path, required=True)
    parser.add_argument('--transcripts', type=Path, required=True)
    parser.add_argument('--profiles', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new plan path; retain earlier production identities')
    translation = read_json(args.translations)
    validate_voice_namespace(translation)
    profiles = read_json(args.profiles)['profiles']
    voices = []
    ids = set()
    for row in translation['voices']:
        index = row['id']
        if type(index) is not int or not 0 <= index < 479 or index in ids:
            parser.error('Invalid or duplicate voice id')
        ids.add(index)
        if row['speaker'] not in profiles or not row['text_ptbr'].strip():
            parser.error('Missing translation or voice profile')
        source = args.catalogue / 'audio' / f'{index:04}.wav'
        with wave.open(str(source)) as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 22050):
                parser.error('Unexpected catalogue audio format')
            seconds = audio.getnframes() / audio.getframerate()
        transcript = args.transcripts / f'{index:04}.json'
        voices.append(dict(row, duration_seconds=seconds, approved_text=True, approved_audio=False,
                           original_audio=str(source.resolve()),
                           original_audio_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                           source_asr_en=read_json(transcript)['text'].strip(),
                           source_asr_note='Automatic source transcript may misspell names; translation reviewed in story context.'))
    atomic_json(args.output, dict(schema=1, resource_kind="voices.dat", profiles=profiles, voices=voices,
                                 source_translation=str(args.translations.resolve()),
                                 human_listening_approved=False))
    print(json.dumps(dict(plan=str(args.output), voices=len(voices))))


if __name__ == '__main__':
    main()
