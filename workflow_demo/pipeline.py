"""Original, synthetic creative workflow. No vendor calls or proprietary prompts."""
from pathlib import Path
from typing import Protocol
import json
import re

def clean_filename(value: str) -> str:
    return re.sub(r'[^A-Za-z0-9_.-]', '_', Path(value).name).strip('._') or 'item'

def analyze(brief: dict) -> dict:
    scenes = brief.get('scenes', [])
    if not isinstance(scenes, list) or not scenes or len(scenes) > 50:
        raise ValueError('Expected 1-50 fictional scenes')
    return {
        'title': str(brief.get('title', 'Untitled'))[:100],
        'style': str(brief.get('style', 'original hand-painted animation'))[:160],
        'scenes': [
            {'description': str(s.get('description', ''))[:700],
             'characters': [str(c)[:70] for c in s.get('characters', [])[:12]],
             'mood': str(s.get('mood', 'calm'))[:80]}
            for s in scenes
        ],
    }

def storyboard(data: dict) -> dict:
    return {'title': data['title'], 'style': data['style'], 'shots': [
        {'shot_id': f'shot-{i:03d}', 'description': s['description'],
         'characters': s['characters'], 'mood': s['mood'], 'framing': 'wide establishing view' if i == 1 else 'medium shot',
         'duration_sec': 4}
        for i, s in enumerate(data['scenes'], start=1)]}

def prompts(data: dict) -> dict:
    return {'title': data['title'], 'shots': [
        {'shot_id': s['shot_id'], 'duration_sec': s['duration_sec'],
         'prompt': 'Create an original animated scene. Style: ' + data['style'] +
                   '. Framing: ' + s['framing'] + '. Characters: ' +
                   ', '.join(s['characters']) + '. Action: ' + s['description'] +
                   '. Mood: ' + s['mood'] +
                   '. Readable staging and smooth motion. No titles, brand marks or watermarks.',
         'negative_prompt': 'real-person likeness, logos, copyrighted characters, watermarks',
         'requested_output': 'mp4'} for s in data['shots']]}

class VideoBackend(Protocol):
    def render(self, shot: dict, directory: Path) -> dict: ...

class MockVideoBackend:
    """Simulates renders; never produces media files or calls an API."""
    def render(self, shot: dict, directory: Path) -> dict:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (clean_filename(shot['shot_id']) + '.render.json')
        receipt = {'shot_id': shot['shot_id'], 'backend': 'mock',
                   'status': 'simulated', 'actual_video_generated': False}
        path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        return {'shot_id': shot['shot_id'], 'receipt': str(path.name), 'status': 'simulated'}

def execute(stage: str, payload: dict, output_dir: Path, backend: VideoBackend) -> dict:
    if stage == 'analyze':
        return analyze(payload)
    if stage == 'storyboard':
        return storyboard(payload)
    if stage == 'prompts':
        result = prompts(payload)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / 'prompts.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
    if stage == 'render':
        receipts = [backend.render(s, output_dir / 'renders') for s in payload['shots']]
        return {'title': payload['title'], 'clips': receipts}
    if stage == 'deliver':
        result = {'title': payload['title'], 'render_backend': 'mock',
                  'clips': payload['clips']}
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / 'delivery.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
    raise ValueError('Unsupported stage')
