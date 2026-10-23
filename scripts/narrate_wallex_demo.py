"""Synthesize public Persian demo text using Edge TTS, without account credentials.

Optional video-production tool, separate from the trading engine. Requires edge-tts.
This sends only the provided public narration to the Edge speech service.
"""
import argparse
import asyncio
import json
from pathlib import Path


async def generate(script, output):
    import edge_tts
    output.mkdir(parents=True, exist_ok=True)
    segments = json.loads(script.read_text())
    limit = asyncio.Semaphore(2)

    async def one(index, segment):
        async with limit:
            destination = output / f'{index + 1}.mp3'
            await asyncio.wait_for(edge_tts.Communicate(
                segment['text'], voice='fa-IR-FaridNeural', rate='-8%'
            ).save(str(destination)), 90)
            return {'segment': index + 1, 'file': destination.name,
                    'bytes': destination.stat().st_size}

    results = await asyncio.gather(*(one(i, x) for i, x in enumerate(segments)))
    report = {'provider': 'Microsoft Edge public speech service via edge-tts',
              'voice': 'fa-IR-FaridNeural', 'synthetic_narration': True,
              'billing_credentials_used': False, 'paid_resource_created': False,
              'segments': results}
    (output / 'generation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--script', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(generate(args.script, args.output))
