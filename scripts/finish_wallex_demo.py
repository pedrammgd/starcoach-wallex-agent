"""Encode the local-only recorded evidence UI as a shareable H.264/AAC MP4.

Run after record_final_wallex_demo.cjs. The AAC track is silence, not narration.
No provider or exchange API is used by this script.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--ffmpeg', default=shutil.which('ffmpeg'))
    parser.add_argument('--recording', type=Path, default=Path('artifacts/wallex-demo-video/recording.json'))
    parser.add_argument('--output', type=Path, default=Path('artifacts/wallex-final-demo.mp4'))
    args = parser.parse_args()
    if not args.ffmpeg:
        parser.error('Install official FFmpeg or supply --ffmpeg')
    recording = json.loads(args.recording.read_text())
    source = Path(recording['video'])
    if not source.is_file():
        parser.error('Recorded video not found')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    command = [args.ffmpeg, '-hide_banner', '-y', '-ss', '1', '-i', str(source),
               '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
               '-map', '0:v:0', '-map', '1:a:0', '-map_metadata', '-1',
               '-vf', 'fps=25,format=yuv420p', '-c:v', 'libx264',
               '-preset', 'veryfast', '-crf', '22', '-c:a', 'aac',
               '-b:a', '96k', '-t', '300', '-shortest', '-movflags', '+faststart',
               '-metadata', 'title=Wallex recorded evidence demo - historical replay',
               str(args.output)]
    subprocess.run(command, check=True)
    probe = subprocess.run([args.ffmpeg, '-hide_banner', '-i', str(args.output)],
                           text=True, capture_output=True).stderr
    duration = re.search(r'Duration: (\d+):(\d+):([\d.]+)', probe)
    seconds = (int(duration[1])*3600 + int(duration[2])*60 + float(duration[3])) if duration else None
    if not (seconds and 295 <= seconds <= 320 and '1920x1080' in probe
            and 'Video: h264' in probe and 'Audio: aac' in probe):
        raise RuntimeError('Unexpected video codec, dimensions, audio or duration')
    decode = subprocess.run([args.ffmpeg, '-v', 'error', '-i', str(args.output), '-f', 'null', '-'],
                            text=True, capture_output=True)
    if decode.returncode or decode.stderr.strip():
        raise RuntimeError('Full video decode failed')
    summary = {
        'file': args.output.name, 'bytes': args.output.stat().st_size,
        'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(),
        'duration_seconds': seconds, 'width': 1920, 'height': 1080,
        'video_codec': 'H.264', 'audio_codec': 'AAC stereo silence',
        'narration': False, 'persian_burned_in_captions': True,
        'actual_browser_recording': True, 'historical_evidence_replay': True,
        'synthetic_section': 'cutoff', 'full_decode_passed': True,
        'real_exchange_orders': 0, 'external_network_requests_allowed': False,
        'publicly_published': False,
    }
    summary_path = args.output.with_suffix('.qa.json')
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
