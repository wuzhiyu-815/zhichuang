"""Audio inspection: blind listening plus independent transcript comparison."""
import difflib
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import weakref
from pathlib import Path

import requests

LOCK = threading.Lock()
RECORD_LOCKS = weakref.WeakValueDictionary()


def record_lock(key):
    with LOCK:
        lock = RECORD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            RECORD_LOCKS[key] = lock
        return lock

DEFAULT_ASR = 'http://192.168.31.210:8101'
DEFAULT_REVIEW = 'http://192.168.31.210:8102'


def compare_dialogue(expected, actual):
    normalize = lambda value: ''.join(c for c in str(value).casefold() if c.isalnum())
    a, b = normalize(expected), normalize(actual)
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    changes = [{'type': tag, 'expected': a[i:j], 'actual': b[k:l]}
               for tag, i, j, k, l in matcher.get_opcodes() if tag != 'equal']
    return {'status': 'matched' if a == b else 'needs_review', 'expected': expected,
            'actual': actual, 'similarity': matcher.ratio(), 'differences': changes,
            'note': '转写可能误识别人名、同音字；差异需复核，不据此自动重制。'}


def offset_items(items, offset):
    result = []
    for value in items or []:
        item = dict(value)
        for key in ('start', 'end'):
            if isinstance(item.get(key), (int, float)):
                item[key] += offset
        result.append(item)
    return result


def request_json(session, base, route, path=None, data=None):
    url = base.rstrip('/') + route
    for attempt in range(2):
        if path:
            with open(path, 'rb') as f:
                response = session.post(url, files={'file': (Path(path).name, f, 'audio/wav')},
                                        data=data or {}, timeout=(8, 120))
        else:
            response = session.get(url, timeout=(8, 10))
        if response.status_code == 502 and attempt == 0:
            continue
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError('音频接口返回格式无效')
        return result


def review(engine, shot, video_path):
    config = engine.runtime_config()
    if not config.get('audio_review_enabled', True):
        return {'status': 'disabled', 'passed': False}
    asr = config.get('audio_asr_url') or DEFAULT_ASR
    listen = config.get('audio_review_url') or DEFAULT_REVIEW
    expected = '\n'.join(str(d.get('line', '')).strip() for d in shot.get('dialogue', []) if d.get('line'))
    speakers = len({d.get('speaker') for d in shot.get('dialogue', []) if d.get('line') and d.get('speaker')})
    stamp = [os.path.abspath(video_path), os.stat(video_path).st_mtime_ns,
             os.path.getsize(video_path), expected, speakers, shot.get('duration'), asr, listen, 1]
    key = hashlib.sha256(json.dumps(stamp, ensure_ascii=False).encode()).hexdigest()[:24]
    directory = Path(engine.REVIEWS_DIR) / 'audio'
    directory.mkdir(parents=True, exist_ok=True)
    record = directory / (key + '.json')
    with record_lock(str(record)):
        if record.exists():
            cached = json.loads(record.read_text())
            if cached.get('status') != 'incomplete':
                return cached
        report = {'status': 'incomplete', 'passed': False, 'segments': [], 'errors': [],
                  'problems': [], 'report_path': str(record), 'video_path': video_path}
        try:
            with requests.Session() as session, tempfile.TemporaryDirectory(prefix='audio-review-') as tmp:
                session.trust_env = False
                for base in (asr, listen):
                    health = request_json(session, base, '/health')
                    if health.get('model_ready') is not True:
                        raise ValueError('音频服务模型未就绪：' + base)
                # WAV parts stay below the service's 30-second ceiling.
                subprocess.run([engine.find_ffmpeg() or 'ffmpeg', '-y', '-v', 'error', '-i', video_path,
                                '-vn', '-c:a', 'pcm_s16le',
                                '-f', 'segment', '-segment_time', '25', os.path.join(tmp, '%04d.wav')],
                               check=True, capture_output=True, timeout=120)
                import wave
                offset = 0.0
                texts = []
                files = sorted(Path(tmp).glob('*.wav'))
                if not files:
                    raise ValueError('视频无可提取音轨')
                for part in files:
                    with wave.open(str(part)) as wav:
                        duration = wav.getnframes() / wav.getframerate()
                    entry = {'offset': offset, 'duration': duration}
                    report['segments'].append(entry)
                    for name, base, route, fields in (
                        ('transcription', asr, '/v1/audio/transcriptions', {'language': 'zh', 'word_timestamps': 'true'}),
                        ('analysis', listen, '/v1/audio/analyze', {'script': expected, 'expected_duration': duration}),
                    ):
                        try:
                            entry[name] = request_json(session, base, route, str(part), fields)
                        except Exception as exc:
                            report['errors'].append(f'{offset:.2f}s {name}: {exc}')
                    trans = entry.get('transcription', {})
                    if not isinstance(trans.get('text'), str):
                        report['errors'].append('转写缺少text')
                    else:
                        texts.append(trans['text'])
                    entry['words'] = offset_items(trans.get('words'), offset)
                    analysis = entry.get('analysis', {})
                    report['problems'].extend(offset_items(analysis.get('problems'), offset))
                    speech, measured = analysis.get('speech') or {}, analysis.get('ffmpeg') or {}
                    if (not isinstance(analysis.get('pass'), bool) or not isinstance(analysis.get('problems'), list)
                        or speech.get('clarity_score') is None or speech.get('speaker_count') is None
                        or measured.get('track_present') is not True or measured.get('clipping_risk') is None
                        or analysis.get('measurement_errors')):
                        report['errors'].append(f'{offset:.2f}s 听音或测量信息不完整')
                    offset += duration
                report['dialogue'] = compare_dialogue(expected, ''.join(texts))
                report['duration'] = offset
                report['expected_speakers'] = speakers
                # A count across independent chunks cannot establish speaker identity.
                report['speakers_match'] = (report['segments'][0].get('analysis', {}).get('speech', {}).get('speaker_count') == speakers
                                            if len(files) == 1 and report['segments'][0].get('analysis', {}).get('speech') else None)
                if report['speakers_match'] is False:
                    report['passed'] = False
                    if report['status'] != 'incomplete':
                        report['status'] = 'needs_review'
                report['duration_delta'] = offset - float(shot.get('duration') or offset)
                report['passed'] = (not report['errors'] and report['speakers_match'] is not False and report['dialogue']['status'] == 'matched'
                                    and all(x.get('analysis', {}).get('pass') is True for x in report['segments']))
                report['status'] = 'incomplete' if report['errors'] else ('passed' if report['passed'] else 'needs_review')
        except Exception as exc:
            report['errors'].append(str(exc))
        temp = record.with_suffix('.tmp')
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        temp.replace(record)
        return report
