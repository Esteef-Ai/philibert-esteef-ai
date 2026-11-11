"""Kokoro: the natural voice for Talk on the phone (Philibert's Android app).

The phone listens and the computer thinks; with this the computer also speaks. Each sentence of a
Talk reply is turned into audio here and played by the phone, which fetches the next sentence while
one plays. Kokoro v1.0 (82M parameters, Apache-2.0) through kokoro-onnx, on the processor, so it
never competes with the chat model for the graphics card: ~2.4x faster than real time measured on
the home PC (8 s of speech in 3.4 s, 2026-11-10).

  <drive>/speech/kokoro/kokoro-v1.0.onnx, voices-v1.0.bin   (or ND_KOKORO_DIR)

Entry points: available(root), voices(root), wav(root, text, voice, speed).
"""
import io
import os
import threading
import wave
from pathlib import Path

DEFAULT_VOICE = "af_heart"
MAX_CHARS = 600                       # one sentence or two; the phone sends sentence by sentence
_engine = {"k": None, "dir": None}
_lock = threading.Lock()              # one synthesis at a time (onnxruntime uses all the cores anyway)

# the English voices worth offering, best first, with a word on each (the rest are other languages)
LABELS = {
    "af_heart": "Heart - warm, natural (US, female)",
    "af_bella": "Bella - bright, expressive (US, female)",
    "af_nicole": "Nicole - soft, close (US, female)",
    "af_sarah": "Sarah - clear (US, female)",
    "af_nova": "Nova (US, female)",
    "af_sky": "Sky (US, female)",
    "am_michael": "Michael - steady, warm (US, male)",
    "am_fenrir": "Fenrir - deep (US, male)",
    "am_puck": "Puck - lively (US, male)",
    "am_echo": "Echo (US, male)",
    "am_eric": "Eric (US, male)",
    "am_liam": "Liam (US, male)",
    "am_onyx": "Onyx - low (US, male)",
    "am_adam": "Adam (US, male)",
    "bf_emma": "Emma (British, female)",
    "bf_isabella": "Isabella (British, female)",
    "bf_alice": "Alice (British, female)",
    "bf_lily": "Lily (British, female)",
    "bm_george": "George (British, male)",
    "bm_fable": "Fable (British, male)",
    "bm_lewis": "Lewis (British, male)",
    "bm_daniel": "Daniel (British, male)",
}


def model_dir(root):
    return Path(os.environ.get("ND_KOKORO_DIR") or (Path(root) / "speech" / "kokoro"))


def _files(root):
    d = model_dir(root)
    return d / "kokoro-v1.0.onnx", d / "voices-v1.0.bin"


def available(root):
    """Kokoro is installed here: the package and both model files."""
    try:
        import importlib.util
        if importlib.util.find_spec("kokoro_onnx") is None:
            return False
    except Exception:
        return False
    return all(f.is_file() for f in _files(root))


def _load(root):
    d = model_dir(root)
    if _engine["k"] is None or _engine["dir"] != d:
        from kokoro_onnx import Kokoro
        onnx, voices_bin = _files(root)
        _engine["k"] = Kokoro(str(onnx), str(voices_bin))
        _engine["dir"] = d
    return _engine["k"]


def voices(root):
    """[{id, label}] - the English voices, best first."""
    if not available(root):
        return []
    with _lock:
        have = set(_load(root).get_voices())
    return [{"id": v, "label": label} for v, label in LABELS.items() if v in have]


def wav(root, text, voice=None, speed=1.0):
    """One sentence -> WAV bytes (16-bit mono, Kokoro's 24 kHz)."""
    import numpy as np
    text = " ".join(str(text or "").split())[:MAX_CHARS]
    if not text:
        raise ValueError("nothing to say")
    voice = voice if voice in LABELS else DEFAULT_VOICE
    try:
        speed = min(1.6, max(0.6, float(speed or 1.0)))
    except (TypeError, ValueError):
        speed = 1.0
    lang = "en-gb" if voice.startswith("b") else "en-us"
    with _lock:
        audio, rate = _load(root).create(text, voice=voice, speed=speed, lang=lang)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm)
    return out.getvalue()


def warm(root):
    """Load the model ahead of the first sentence (2 s), in the background - once."""
    if _engine["k"] is None and available(root):
        threading.Thread(target=lambda: wav(root, "Hi."), daemon=True).start()
