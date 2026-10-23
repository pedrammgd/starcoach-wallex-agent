"""Mix six synthetic Persian narrations with preserved genuine demo footage.

Requires FFmpeg, Pillow, arabic-reshaper and python-bidi (video tools only).
No network requests, credentials or trading operations.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def run(command):
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ffmpeg', required=True)
    p.add_argument('--font', required=True)
    p.add_argument('--source', type=Path, default=Path('artifacts/wallex-final-demo.mp4'))
    p.add_argument('--audio-dir', type=Path, default=Path('artifacts/wallex-narration'))
    p.add_argument('--output', type=Path, default=Path('artifacts/wallex-final-demo-with-voice.mp4'))
    args = p.parse_args()
    from PIL import Image, ImageDraw, ImageFont
    import arabic_reshaper
    from bidi.algorithm import get_display

    original_hash = hashlib.sha256(args.source.read_bytes()).hexdigest()
    segments = json.loads((args.audio_dir / 'script.json').read_text())
    measurements = []
    for i, segment in enumerate(segments, 1):
        source = args.audio_dir / f'{i}.mp3'
        probe = subprocess.run([args.ffmpeg, '-hide_banner', '-i', str(source)], capture_output=True, text=True).stderr
        m = re.search(r'Duration: (\d+):(\d+):([\d.]+)', probe)
        seconds = int(m[1])*3600 + int(m[2])*60 + float(m[3])
        target = segment['duration'] - 2
        tempo = seconds / target
        if not .75 <= tempo <= 1.3:
            raise ValueError('Narration speed adjustment exceeds intelligibility limit')
        destination = args.audio_dir / f'{i}.wav'
        run([args.ffmpeg, '-y', '-i', str(source), '-af',
             f'atempo={tempo:.8f},loudnorm=I=-16:TP=-1.5:LRA=11,adelay=1000:all=1,apad',
             '-t', str(segment['duration']), '-ar', '48000', '-ac', '2', str(destination)])
        measurements.append({'scene': i, 'start': segment['start'],
                             'duration': segment['duration'], 'source_speech_seconds': seconds,
                             'tempo_adjustment': tempo})
    concat = args.audio_dir / 'concat.txt'
    concat.write_text(''.join(f"file '{i}.wav'\n" for i in range(1, 7)))
    narration = args.audio_dir / 'narration.wav'
    run([args.ffmpeg, '-y', '-f', 'concat', '-safe', '0', '-i', str(concat), '-c:a', 'pcm_s16le', str(narration)])

    banner = Image.new('RGB', (1920, 44), '#381e00')
    draw = ImageDraw.Draw(banner)
    font = ImageFont.truetype(args.font, 22)
    label = get_display(arabic_reshaper.reshape('روایت فارسی مصنوعی • بازپخش شواهد ثبت‌شده • هیچ معامله یا عملیات زنده‌ای در فیلم انجام نمی‌شود'))
    draw.text((960, 21), label, font=font, fill='#ffe1a2', anchor='mm')
    banner_path = args.audio_dir / 'synthetic-label.png'
    banner.save(banner_path)
    run([args.ffmpeg, '-y', '-i', str(args.source), '-i', str(narration), '-i', str(banner_path),
         '-filter_complex', '[0:v][2:v]overlay=0:0[v]', '-map', '[v]', '-map', '1:a:0',
         '-map_metadata', '-1', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
         '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', '-t', '300',
         '-movflags', '+faststart', '-metadata', 'title=Wallex historical evidence with synthetic Persian narration',
         str(args.output)])
    run([args.ffmpeg, '-v', 'error', '-i', str(args.output), '-f', 'null', '-'])
    assert hashlib.sha256(args.source.read_bytes()).hexdigest() == original_hash
    summary = {'file': args.output.name, 'duration_seconds': 300, 'width': 1920, 'height': 1080,
               'video_codec': 'H264', 'audio_codec': 'AAC', 'narration': 'synthetic Persian fa-IR-FaridNeural',
               'synthetic_label_burned_in': True, 'original_preserved': True,
               'source_sha256': original_hash, 'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(),
               'bytes': args.output.stat().st_size, 'full_decode_passed': True,
               'segments': measurements, 'real_orders': 0, 'new_AI_inference_during_video': False}
    args.output.with_suffix('.qa.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
