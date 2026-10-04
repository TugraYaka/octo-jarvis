import glob
import os
import queue
import threading

from core import paths

paths.apply_cache_env()
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

import numpy as np

SAMPLE_RATE = 16000
BLOCK_DURATION = 0.05
SILENCE_DURATION = 1.0
MAX_DURATION = 15
NO_SPEECH_TIMEOUT = 4.0
CALIBRATION_DURATION = 0.3
SPEECH_MARGIN = 3.0
MIN_THRESHOLD = 0.005
TRIM_PADDING_BLOCKS = 4
CPU_THREADS = min(10, os.cpu_count() or 4)
LANGUAGE = "tr"

def _local_model_path():
    pattern = os.path.join(
        os.environ["HF_HOME"], "hub", "models--Systran--faster-whisper-small", "snapshots", "*"
    )
    matches = glob.glob(pattern)
    return matches[0] if matches else None


def _import_sounddevice():
    try:
        import sounddevice
    except OSError as e:
        raise RuntimeError(
            "Microphone support needs the PortAudio library "
            "(Linux: sudo apt install libportaudio2)."
        ) from e
    return sounddevice


_model = None
_model_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from faster_whisper import WhisperModel

                _model = WhisperModel(
                    _local_model_path() or "small",
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=CPU_THREADS,
                )
    return _model


def is_cached() -> bool:
    return _local_model_path() is not None


def load() -> None:
    _get_model()


def warmup():
    if not is_cached():
        return
    model = _get_model()
    silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
    list(model.transcribe(silence, language="tr", vad_filter=True, beam_size=1)[0])


def _trim(frames: list, loud_flags: list) -> np.ndarray:
    if not any(loud_flags):
        return np.array([], dtype=np.float32)
    first = max(0, loud_flags.index(True) - TRIM_PADDING_BLOCKS)
    last = min(len(frames), len(loud_flags) - loud_flags[::-1].index(True) + TRIM_PADDING_BLOCKS)
    return np.concatenate(frames[first:last]).flatten()


def record_until_silence() -> np.ndarray:
    sd = _import_sounddevice()
    block_size = int(SAMPLE_RATE * BLOCK_DURATION)
    blocks: queue.Queue = queue.Queue()

    def callback(indata, frame_count, time_info, status):
        blocks.put(indata.copy())

    frames = []
    loud_flags = []
    noise_samples = []
    threshold = MIN_THRESHOLD
    silence_needed = int(SILENCE_DURATION / BLOCK_DURATION)
    silent_blocks = 0
    started = False
    elapsed = 0.0

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=block_size,
        callback=callback,
    ):
        while elapsed < MAX_DURATION:
            try:
                block = blocks.get(timeout=1.0)
            except queue.Empty:
                break
            elapsed += BLOCK_DURATION
            volume = float(np.abs(block).mean())

            if elapsed <= CALIBRATION_DURATION:
                noise_samples.append(volume)
                continue
            if noise_samples:
                floor = max(sum(noise_samples) / len(noise_samples), 1e-5)
                threshold = max(floor * SPEECH_MARGIN, MIN_THRESHOLD)
                noise_samples = []

            is_loud = volume > threshold
            frames.append(block)
            loud_flags.append(is_loud)

            if is_loud:
                started = True
                silent_blocks = 0
            elif started:
                silent_blocks += 1
                if silent_blocks >= silence_needed:
                    break
            elif elapsed >= NO_SPEECH_TIMEOUT:
                return np.array([], dtype=np.float32)

    if not frames:
        return np.array([], dtype=np.float32)
    return _trim(frames, loud_flags)


def _decode(audio: np.ndarray):
    segments, info = _get_model().transcribe(
        audio,
        language=LANGUAGE,
        vad_filter=True,
        beam_size=1,
        condition_on_previous_text=False,
    )
    return segments, info.language


def transcribe(audio: np.ndarray):
    segments, language = _decode(audio)
    text = " ".join(segment.text.strip() for segment in segments)
    return text.strip(), language


def transcribe_stream(audio: np.ndarray):
    segments, language = _decode(audio)
    for segment in segments:
        yield segment.text.strip(), language


def listen():
    audio = record_until_silence()
    if audio.size == 0:
        return "", None
    return transcribe(audio)


def listen_stream():
    audio = record_until_silence()
    if audio.size == 0:
        return
    yield from transcribe_stream(audio)
