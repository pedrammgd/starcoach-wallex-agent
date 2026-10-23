"""Local ASR only; requires .tools/video environment, never uploads the video."""
import json
from pathlib import Path
import subprocess

import imageio_ffmpeg
from faster_whisper import WhisperModel

root=Path(__file__).resolve().parent.parent
audio=root/'.tools/challenge.wav'
subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-i',str(root/'WALLEX_CHALLENGE_VIDEO.mp4'),
                '-vn','-ac','1','-ar','16000',str(audio)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
model=WhisperModel('small',device='cpu',compute_type='int8',download_root=str(root/'.tools/models'),cpu_threads=4)
segments,info=model.transcribe(str(audio),language='fa',beam_size=5,vad_filter=True)
out=root/'docs/VIDEO_TRANSCRIPT_AUTO_FA.md'
out.write_text('# رونویسی خودکار ویدئوی چالش\n\nخروجی ASR محلی؛ اعداد، نمادها و مهلت‌ها نیاز به مقابله با منبع رسمی دارند.\n\n')
with out.open('a') as f:
 for s in segments:
  line=f'[{s.start:.1f}–{s.end:.1f}] {s.text}\n'
  f.write(line);f.flush();print(line,flush=True)
print(json.dumps({'language':info.language,'duration':info.duration,'path':str(out)}),flush=True)
