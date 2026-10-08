import json
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ.setdefault("COQUI_TOS_AGREED", "1")

from TTS.api import TTS
from TTS.tts.configs.xtts_config import XttsConfig
from TTS.tts.models.xtts import Xtts
from TTS.utils.manage import ModelManager

PORT = 8765
SERVICE_ID = "jarvis-tts"
BASE_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
DEFAULT_SPEAKER = "Ana Florence"
TR_SPEED = 1.25
SUPPORTED_LANGS = frozenset(
    ["en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar", "zh-cn", "hu", "ko", "ja", "hi"]
)

ASSETS_DIR = os.environ.get("JARVIS_ASSETS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "assets"
)
VOICES_DIR = os.path.join(ASSETS_DIR, "voices")
TR_MODEL_DIR = os.path.join(ASSETS_DIR, "models", "tr_finetuned")
TR_CONFIG = os.path.join(TR_MODEL_DIR, "config.json")
TR_CHECKPOINT = os.path.join(TR_MODEL_DIR, "model.pth")
TR_VOCAB = os.path.join(TR_MODEL_DIR, "vocab.json")
TR_SPEAKER_REF = os.path.join(TR_MODEL_DIR, "speaker_ref.wav")

print(f"Assets folder: {ASSETS_DIR}")

base_model_dir, _, _ = ModelManager().download_model(BASE_MODEL)
base_tts = None


def get_base_tts():
    global base_tts
    if base_tts is None:
        base_tts = TTS(BASE_MODEL)
    return base_tts


tr_model = None
TR_LATENTS = None
if os.path.exists(TR_CHECKPOINT):
    missing = [p for p in (TR_CONFIG, TR_VOCAB, TR_SPEAKER_REF) if not os.path.exists(p)]
    if missing:
        print(f"Fine-tuned Turkish model found but incomplete, missing: {', '.join(missing)}")
    else:
        print("Loading fine-tuned Turkish XTTS model...")
        tr_config = XttsConfig()
        tr_config.load_json(TR_CONFIG)
        tr_model = Xtts.init_from_config(tr_config)
        tr_model.load_checkpoint(
            tr_config,
            checkpoint_path=TR_CHECKPOINT,
            vocab_path=TR_VOCAB,
            speaker_file_path=os.path.join(base_model_dir, "speakers_xtts.pth"),
            use_deepspeed=False,
        )
        tr_model.eval()
        TR_LATENTS = tr_model.get_conditioning_latents(audio_path=[TR_SPEAKER_REF])
        print("Fine-tuned Turkish model loaded.")
else:
    print(f"No fine-tuned Turkish model at {TR_MODEL_DIR}; using the voice files or the default voice.")

print("Model loading complete. Server ready.")


def reference_voices(lang):
    if not os.path.isdir(VOICES_DIR):
        return []
    match = [n for n in os.listdir(VOICES_DIR) if n == lang]
    if not match:
        return []
    lang_dir = os.path.join(VOICES_DIR, match[0])
    if not os.path.isdir(lang_dir):
        return []
    return sorted(
        os.path.join(lang_dir, f) for f in os.listdir(lang_dir) if f.lower().endswith(".wav")
    )


def default_speaker(tts):
    names = list(tts.synthesizer.tts_model.speaker_manager.speakers.keys())
    return DEFAULT_SPEAKER if DEFAULT_SPEAKER in names else names[0]


def synthesize(text, lang, out_path):
    if lang == "tr" and tr_model is not None:
        import torch
        import torchaudio

        gpt_cond_latent, speaker_embedding = TR_LATENTS
        out = tr_model.inference(text, "tr", gpt_cond_latent, speaker_embedding, speed=TR_SPEED)
        torchaudio.save(out_path, torch.tensor(out["wav"]).unsqueeze(0), 24000)
        return

    tts = get_base_tts()
    voices = reference_voices(lang)
    if voices:
        tts.tts_to_file(text=text, speaker_wav=voices, language=lang, file_path=out_path)
        return
    tts.tts_to_file(text=text, speaker=default_speaker(tts), language=lang, file_path=out_path)


class Handler(BaseHTTPRequestHandler):
    def _reply(self, status, body, content_type="text/plain; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._reply(200, json.dumps({"service": SERVICE_ID}).encode(), "application/json")

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            text = body["text"]
            lang = body.get("lang", "tr")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("text must be a non-empty string")
            if lang not in SUPPORTED_LANGS:
                raise ValueError("unsupported language")
        except (ValueError, KeyError, TypeError) as e:
            self._reply(400, f"Bad request: {e}".encode())
            return

        raw_path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        try:
            synthesize(text, lang, raw_path)
            with open(raw_path, "rb") as f:
                data = f.read()
        except Exception as e:
            print(f"Synthesis failed: {e}", file=sys.stderr)
            self._reply(500, f"Synthesis failed: {e}".encode())
            return
        finally:
            os.remove(raw_path)

        self._reply(200, data, "audio/wav")

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    print(f"Listening on http://127.0.0.1:{PORT}")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
