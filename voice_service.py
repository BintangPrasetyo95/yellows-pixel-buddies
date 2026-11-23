"""voice_service.py - Push-to-Talk Microphone Recording & Local Whisper / Gemini Transcription Engine.

Part of Yellow's Pixel Buddies / Pink desktop companion.
Provides:
- Robust microphone capture supporting WASAPI, DirectSound, and MME devices on Windows.
- Automatic device sample-rate detection and high-fidelity linear resampling to 16kHz float32.
- Adaptive gain normalization so quiet laptop microphones are transcribed accurately.
- Real-time RMS audio level calculation for retro HUD animations.
- Asynchronous local Whisper speech-to-text transcription worker (QThread).
- Cloud Gemini multimodal audio fallback (gemini-3.5-flash-lite) if local Whisper is unavailable.
- Lazy model preloading in background to ensure near-instant transcription.
"""

from __future__ import annotations

import base64
import io
import logging
import os
from pathlib import Path
import site
import sys
import threading
import time
import wave
from typing import Callable, List, Optional, Tuple

import numpy as np

# Resolve Windows PyTorch DLLs if on Python 3.8+ on Windows
_DLL_HANDLES: list = []
if sys.platform == "win32":
    candidate_paths = []
    try:
        candidate_paths.extend(site.getsitepackages())
    except Exception:
        pass
    try:
        user_site = site.getusersitepackages()
        if user_site:
            candidate_paths.append(user_site)
    except Exception:
        pass
    for sp in candidate_paths:
        t_lib = Path(sp) / "torch" / "lib"
        if t_lib.exists():
            try:
                os.environ["PATH"] = str(t_lib) + os.pathsep + os.environ.get("PATH", "")
                if hasattr(os, "add_dll_directory"):
                    _DLL_HANDLES.append(os.add_dll_directory(str(t_lib)))
            except Exception:
                pass

# Import whisper/torch BEFORE sounddevice to avoid C-level DLL initialization conflict on Windows
_WHISPER_ERR = None
try:
    import whisper
    HAS_WHISPER = True
except Exception as exc:
    _WHISPER_ERR = str(exc)
    HAS_WHISPER = False

try:
    from PyQt5.QtCore import QObject, QThread, pyqtSignal
    HAS_PYQT = True
except Exception:
    HAS_PYQT = False

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except Exception:
    HAS_SOUNDDEVICE = False

try:
    import requests
    HAS_REQUESTS = True
except Exception:
    HAS_REQUESTS = False

log = logging.getLogger("yellows_pixel_buddies.voice")

TARGET_SAMPLE_RATE = 16000  # Whisper native sample rate


def resample_audio(audio_data: np.ndarray, orig_sr: int, target_sr: int = TARGET_SAMPLE_RATE) -> np.ndarray:
    """Resample 1D float32 audio to target sample rate using fast linear interpolation."""
    if orig_sr == target_sr or len(audio_data) == 0:
        return audio_data.astype(np.float32)
    num_target_samples = int(len(audio_data) * target_sr / orig_sr)
    if num_target_samples == 0:
        return np.zeros(0, dtype=np.float32)
    x_orig = np.linspace(0.0, 1.0, len(audio_data))
    x_target = np.linspace(0.0, 1.0, num_target_samples)
    return np.interp(x_target, x_orig, audio_data).astype(np.float32)


def normalize_audio_gain(audio_data: np.ndarray) -> np.ndarray:
    """Apply adaptive gain boost to quiet audio from laptop mic arrays."""
    if len(audio_data) == 0:
        return audio_data
    max_val = float(np.max(np.abs(audio_data)))
    # If audio is soft (< 0.25 peak) but above noise floor (> 0.0005)
    if 0.0005 < max_val < 0.25:
        boost = min(12.0, 0.5 / max_val)
        return np.clip(audio_data * boost, -1.0, 1.0)
    return audio_data


def audio_to_wav_bytes(audio_data: np.ndarray, sample_rate: int = TARGET_SAMPLE_RATE) -> bytes:
    """Convert float32 numpy audio array (-1.0 to 1.0) into 16-bit PCM WAV bytes."""
    clamped = np.clip(audio_data, -1.0, 1.0)
    int16_data = (clamped * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit PCM
        wf.setframerate(sample_rate)
        wf.writeframes(int16_data.tobytes())
    return buf.getvalue()


def find_best_input_device() -> Tuple[Optional[int], int, int]:
    """Find the best input device, native sample rate, and channels.
    
    Prefers Windows WASAPI or DirectSound devices to avoid legacy MME downsampling bugs.
    Returns (device_index, sample_rate, channels).
    """
    if not HAS_SOUNDDEVICE:
        return None, TARGET_SAMPLE_RATE, 1

    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
        
        # 1. Look for WASAPI Microphone
        for i, d in enumerate(devices):
            if d.get("max_input_channels", 0) > 0:
                api_name = hostapis[d["hostapi"]]["name"]
                if "WASAPI" in api_name and "Microphone" in d.get("name", ""):
                    sr = int(d.get("default_samplerate", 48000))
                    ch = min(2, max(1, d.get("max_input_channels", 1)))
                    log.info("Voice: Selected WASAPI input device #%d '%s' (sr=%d, ch=%d)", i, d["name"], sr, ch)
                    return i, sr, ch

        # 2. Look for DirectSound Microphone
        for i, d in enumerate(devices):
            if d.get("max_input_channels", 0) > 0:
                api_name = hostapis[d["hostapi"]]["name"]
                if "DirectSound" in api_name and "Microphone" in d.get("name", ""):
                    sr = int(d.get("default_samplerate", 44100))
                    ch = min(2, max(1, d.get("max_input_channels", 1)))
                    log.info("Voice: Selected DirectSound input device #%d '%s' (sr=%d, ch=%d)", i, d["name"], sr, ch)
                    return i, sr, ch

        # 3. Default input device fallback
        def_info = sd.query_devices(kind="input")
        def_idx = sd.default.device[0]
        sr = int(def_info.get("default_samplerate", 44100))
        ch = min(2, max(1, def_info.get("max_input_channels", 1)))
        log.info("Voice: Selected default input device #%s '%s' (sr=%d, ch=%d)", def_idx, def_info.get("name"), sr, ch)
        return def_idx, sr, ch
    except Exception as exc:
        log.warning("Voice: Error querying input devices (%s), using defaults.", exc)
        return None, TARGET_SAMPLE_RATE, 1


class WhisperLoadThread(QThread if HAS_PYQT else object):
    """Background worker to preload the Whisper model so user turns don't block."""
    if HAS_PYQT:
        sig_loaded = pyqtSignal(object)  # model
        sig_failed = pyqtSignal(str)     # error message

    def __init__(self, model_name: str = "base", parent: Optional[QObject] = None) -> None:
        if HAS_PYQT:
            super().__init__(parent)
        self._model_name = model_name

    def run(self) -> None:
        if not HAS_WHISPER:
            if HAS_PYQT:
                self.sig_failed.emit("openai-whisper package is not available.")
            return
        try:
            log.info("Preloading Whisper model '%s' in background...", self._model_name)
            t0 = time.perf_counter()
            model = whisper.load_model(self._model_name)
            dt = time.perf_counter() - t0
            log.info("Whisper model '%s' loaded successfully in %.2f seconds", self._model_name, dt)
            if HAS_PYQT:
                self.sig_loaded.emit(model)
        except Exception as exc:
            log.exception("Failed to load Whisper model '%s': %s", self._model_name, exc)
            if HAS_PYQT:
                self.sig_failed.emit(str(exc))


class WhisperTranscribeThread(QThread if HAS_PYQT else object):
    """Background worker to transcribe a recorded audio buffer using Whisper with Gemini fallback."""
    if HAS_PYQT:
        sig_transcribed = pyqtSignal(str)
        sig_error = pyqtSignal(str)

    def __init__(
        self,
        audio_data: np.ndarray,
        model: Optional[object] = None,
        model_name: str = "base",
        api_key: str = "",
        language: str = "en",
        parent: Optional[QObject] = None,
    ) -> None:
        if HAS_PYQT:
            super().__init__(parent)
        self._audio_data = audio_data
        self._model = model
        self._model_name = model_name
        self._api_key = api_key
        self._language = language

    def run(self) -> None:
        # Check minimum duration (~0.25 seconds)
        if len(self._audio_data) < int(TARGET_SAMPLE_RATE * 0.25):
            log.info("Audio buffer too short (< 250ms), ignoring.")
            if HAS_PYQT:
                self.sig_transcribed.emit("")
            return

        # Prepare normalized float32 audio
        audio_1d = normalize_audio_gain(self._audio_data.flatten().astype(np.float32))
        max_amp = float(np.max(np.abs(audio_1d)))
        log.info("Transcribing audio buffer (samples=%d, duration=%.2fs, max_amp=%.4f)",
                 len(audio_1d), len(audio_1d) / TARGET_SAMPLE_RATE, max_amp)

        if max_amp < 0.001:
            log.info("Audio buffer appears to be complete silence (max_amp=%.5f).", max_amp)
            if HAS_PYQT:
                self.sig_transcribed.emit("")
            return

        # Attempt 1: Local Whisper
        if HAS_WHISPER:
            try:
                model = self._model
                if model is None:
                    log.info("Whisper model not preloaded, loading '%s' now...", self._model_name)
                    model = whisper.load_model(self._model_name)

                t0 = time.perf_counter()
                whisper_lang = "id" if self._language == "id" else ("en" if self._language == "en" else None)
                result = model.transcribe(
                    audio_1d,
                    fp16=False,
                    language=whisper_lang,
                    temperature=0.0,
                )
                text = (result.get("text") or "").strip()
                dt = time.perf_counter() - t0
                log.info("Local Whisper transcribed (%s) in %.2fs: %r", whisper_lang, dt, text)
                if HAS_PYQT:
                    self.sig_transcribed.emit(text)
                return
            except Exception as exc:
                log.warning("Local Whisper transcription failed, trying cloud fallback: %s", exc)

        # Attempt 2: Cloud Gemini Multimodal Audio Fallback
        if self._api_key and HAS_REQUESTS:
            fallback_models = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-lite-latest"]
            wav_bytes = audio_to_wav_bytes(audio_1d)
            b64_audio = base64.b64encode(wav_bytes).decode("utf-8")
            if self._language == "id":
                prompt_text = "Transcribe the speech in this audio exactly into Bahasa Indonesia (or English if spoken). Return ONLY the transcribed text without quotes or explanations, or nothing if silent."
            else:
                prompt_text = "Transcribe the speech in this audio exactly. Return ONLY the transcribed text, or nothing if silent."
            for model_id in fallback_models:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={self._api_key}"
                    payload = {
                        "contents": [{
                            "parts": [
                                {"text": prompt_text},
                                {
                                    "inline_data": {
                                        "mime_type": "audio/wav",
                                        "data": b64_audio
                                    }
                                }
                            ]
                        }],
                        "generationConfig": {
                            "temperature": 0.0,
                            "maxOutputTokens": 200,
                        }
                    }
                    resp = requests.post(url, json=payload, timeout=8)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            text = "".join(p.get("text", "") for p in parts).strip()
                            log.info("Cloud Gemini (%s) audio transcribed: %r", model_id, text)
                            if HAS_PYQT:
                                self.sig_transcribed.emit(text)
                            return
                except Exception as gemini_exc:
                    log.warning("Cloud Gemini fallback with %s failed: %s", model_id, gemini_exc)

        if HAS_PYQT:
            self.sig_error.emit("Could not transcribe audio. Check mic volume or speak closer.")


class VoiceManager(QObject if HAS_PYQT else object):
    """High-level Push-to-Talk manager combining sounddevice recording with Whisper transcription."""
    if HAS_PYQT:
        sig_recording_started = pyqtSignal()
        sig_recording_stopped = pyqtSignal()
        sig_audio_level = pyqtSignal(float)       # Normalized RMS 0.0 .. 1.0
        sig_transcription_started = pyqtSignal()
        sig_transcription_finished = pyqtSignal(str)
        sig_transcription_error = pyqtSignal(str)
        sig_model_ready = pyqtSignal()

    def __init__(self, model_name: str = "base", api_key: str = "", language: str = "en", parent: Optional[QObject] = None) -> None:
        if HAS_PYQT:
            super().__init__(parent)
        self._model_name = model_name
        self._api_key = api_key
        self._language = language if language in ("en", "id") else "en"
        self._whisper_model: Optional[object] = None
        self._is_recording = False
        self._stream: Optional[sd.InputStream] = None
        self._frames: List[np.ndarray] = []
        self._device_idx: Optional[int] = None
        self._native_sr: int = 48000
        self._native_channels: int = 1
        self._lock = threading.Lock()
        self._load_worker: Optional[WhisperLoadThread] = None
        self._transcribe_worker: Optional[WhisperTranscribeThread] = None

    def set_api_key(self, api_key: str) -> None:
        self._api_key = api_key

    def set_language(self, language: str) -> None:
        """Set active speech transcription language ('en' or 'id')."""
        self._language = language if language in ("en", "id") else "en"

    def preload(self) -> None:
        """Asynchronously load the Whisper model into RAM."""
        if self._whisper_model is not None or (self._load_worker and self._load_worker.isRunning()):
            return
        if not HAS_WHISPER:
            log.info("Whisper not locally available; Gemini cloud audio fallback will be used.")
            return

        self._load_worker = WhisperLoadThread(self._model_name, parent=self)
        self._load_worker.sig_loaded.connect(self._on_model_loaded)
        self._load_worker.sig_failed.connect(self._on_model_failed)
        self._load_worker.start()

    def _on_model_loaded(self, model: object) -> None:
        self._whisper_model = model
        log.info("VoiceManager: Whisper model ready for instant push-to-talk.")
        if HAS_PYQT:
            self.sig_model_ready.emit()

    def _on_model_failed(self, err: str) -> None:
        log.warning("VoiceManager: Failed to preload Whisper model (%s), fallback ready.", err)

    def is_recording(self) -> bool:
        return self._is_recording

    def is_model_ready(self) -> bool:
        return self._whisper_model is not None

    def start_recording(self) -> bool:
        """Begin recording microphone input chunks until stop_recording is called."""
        if self._is_recording:
            return True
        if not HAS_SOUNDDEVICE:
            log.error("Cannot record: sounddevice is not available.")
            if HAS_PYQT:
                self.sig_transcription_error.emit("sounddevice module not available.")
            return False

        with self._lock:
            self._frames.clear()

        # Resolve best hardware device and sample rate
        self._device_idx, self._native_sr, self._native_channels = find_best_input_device()

        def _audio_callback(indata: np.ndarray, frames_count: int, time_info: dict, status: sd.CallbackFlags) -> None:
            if status:
                log.debug("sounddevice stream status: %s", status)
            
            # Average multi-channel array into mono
            if indata.ndim > 1 and indata.shape[1] > 1:
                mono_chunk = np.mean(indata, axis=1)
            else:
                mono_chunk = indata.flatten()

            with self._lock:
                self._frames.append(mono_chunk.copy())

            # Real-time RMS amplitude for Soul Heart / DOKI-METER animation
            try:
                rms = float(np.sqrt(np.mean(mono_chunk**2)))
                norm_level = min(1.0, max(0.0, rms * 15.0))
                if HAS_PYQT:
                    self.sig_audio_level.emit(norm_level)
            except Exception:
                pass

        try:
            self._stream = sd.InputStream(
                samplerate=self._native_sr,
                channels=self._native_channels,
                device=self._device_idx,
                dtype="float32",
                callback=_audio_callback,
            )
            self._stream.start()
            self._is_recording = True
            log.info("VoiceManager: Started microphone recording (device=%s, sr=%d, ch=%d).",
                     self._device_idx, self._native_sr, self._native_channels)
            if HAS_PYQT:
                self.sig_recording_started.emit()
            return True
        except Exception as exc:
            log.exception("VoiceManager: Failed to start audio input stream: %s", exc)
            self._is_recording = False
            if HAS_PYQT:
                self.sig_transcription_error.emit(f"Microphone error: {exc}")
            return False

    def cancel_recording(self) -> None:
        """Stop microphone capture and DISCARD the audio: nothing is transcribed or dispatched.

        Used when the user cancels Voice Mode (Esc, [X], toggle off, quit). Before this existed, cancelling went
        through stop_recording(), so the command was still transcribed and could start a takeover (REVIEW H10).
        """
        was_recording = self._is_recording
        self._is_recording = False
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        except Exception as exc:
            log.warning("Error closing sounddevice stream on cancel: %s", exc)
        finally:
            self._stream = None
        with self._lock:
            self._frames.clear()
        if was_recording:
            log.info("VoiceManager: Recording cancelled; audio discarded.")
            if HAS_PYQT:
                self.sig_recording_stopped.emit()

    def stop_recording(self) -> None:
        """Stop microphone capture, resample to 16kHz, and trigger Whisper transcription."""
        if not self._is_recording:
            return

        self._is_recording = False
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
                self._stream = None
        except Exception as exc:
            log.warning("Error closing sounddevice stream: %s", exc)

        log.info("VoiceManager: Stopped microphone recording.")
        if HAS_PYQT:
            self.sig_recording_stopped.emit()

        with self._lock:
            if not self._frames:
                log.info("No audio frames recorded.")
                if HAS_PYQT:
                    self.sig_transcription_finished.emit("")
                return
            raw_audio = np.concatenate(self._frames, axis=0)

        # Resample native device rate down to 16kHz for Whisper
        resampled_audio = resample_audio(raw_audio, orig_sr=self._native_sr, target_sr=TARGET_SAMPLE_RATE)

        # Launch background transcription worker
        if HAS_PYQT:
            self.sig_transcription_started.emit()
        self._transcribe_worker = WhisperTranscribeThread(
            audio_data=resampled_audio,
            model=self._whisper_model,
            model_name=self._model_name,
            api_key=self._api_key,
            language=self._language,
            parent=self,
        )
        self._transcribe_worker.sig_transcribed.connect(self._on_transcribed)
        self._transcribe_worker.sig_error.connect(self._on_transcribe_error)
        self._transcribe_worker.start()

    def _on_transcribed(self, text: str) -> None:
        log.info("VoiceManager: Transcription complete: %r", text)
        if HAS_PYQT:
            self.sig_transcription_finished.emit(text)

    def _on_transcribe_error(self, err: str) -> None:
        log.error("VoiceManager: Transcription error: %s", err)
        if HAS_PYQT:
            self.sig_transcription_error.emit(err)
