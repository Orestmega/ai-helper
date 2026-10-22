"""
=============================================================================
Ghost Pilot - 100% Hands-Free Autonomous Real-Time AI Copilot for Windows
=============================================================================
Continuously listens to audio (Speaker Loopback, Microphone, or Both),
detects questions automatically, and renders instant answers in a sleek,
semi-transparent desktop overlay that is 100% invisible to screen sharing
(Zoom, Teams, Meet, Discord, OBS) via Windows SetWindowDisplayAffinity.

Supports both Google Gemini and Groq (Ultra-Fast LPU) providers.
=============================================================================
"""

import sys
import os
import io
import time
import math
import ctypes
import queue
import logging
import threading
from datetime import datetime
from typing import Optional, Tuple, List

import numpy as np
import soundcard as sc
import soundfile as sf
import requests
from dotenv import load_dotenv

from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QPoint, pyqtSlot
)
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QCursor, QPalette
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QDialog, QLineEdit,
    QComboBox, QSlider, QMessageBox, QSizeGrip, QSizePolicy
)

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("GhostPilot")

# Load existing environment variables
load_dotenv()

# ---------------------------------------------------------------------------
# Windows Display Affinity Constants (WDA_EXCLUDEFROMCAPTURE)
# ---------------------------------------------------------------------------
WDA_NONE = 0x00000000
WDA_MONITOR = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011  # Windows 10 Version 2004+ and Windows 11


def apply_capture_exclusion(hwnd: int, invisible: bool = True) -> bool:
    """
    If invisible=True: excludes window from screen sharing/capture APIs
    via WDA_EXCLUDEFROMCAPTURE (0x00000011).
    If invisible=False: restores normal capture affinity (0x00000000, WDA_NONE)
    so the user can screenshot or stream the window.
    """
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32
        user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        user32.SetWindowDisplayAffinity.restype = ctypes.c_bool

        if invisible:
            success = user32.SetWindowDisplayAffinity(ctypes.c_void_p(hwnd), WDA_EXCLUDEFROMCAPTURE)
            if not success:
                success = user32.SetWindowDisplayAffinity(ctypes.c_void_p(hwnd), WDA_MONITOR)
        else:
            success = user32.SetWindowDisplayAffinity(ctypes.c_void_p(hwnd), WDA_NONE)
        logger.info(f"Display affinity {'INVISIBLE (0x11)' if invisible else 'VISIBLE (0x0)'} applied to HWND {hwnd}: {bool(success)}")
        return bool(success)
    except Exception as e:
        logger.error(f"Failed to set window display affinity: {e}")
        return False


# ---------------------------------------------------------------------------
# Application Configuration Manager
# ---------------------------------------------------------------------------
class AppConfig:
    """Manages application settings loaded from .env with fallback defaults."""
    ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

    # --- AI Provider (gemini or groq) ---
    @classmethod
    def get_ai_provider(cls) -> str:
        val = os.environ.get("AI_PROVIDER", "groq").strip().lower()
        if val in ("grok", "xai"):
            return "groq"
        return val

    @classmethod
    def set_ai_provider(cls, provider: str):
        val = provider.strip().lower()
        if val in ("grok", "xai"):
            val = "groq"
        os.environ["AI_PROVIDER"] = val
        cls._save_key_val("AI_PROVIDER", val)

    # --- Gemini Settings ---
    @classmethod
    def get_gemini_api_key(cls) -> str:
        return os.environ.get("GEMINI_API_KEY", "").strip()

    @classmethod
    def set_gemini_api_key(cls, key: str):
        os.environ["GEMINI_API_KEY"] = key.strip()
        cls._save_key_val("GEMINI_API_KEY", key.strip())

    @classmethod
    def get_gemini_model(cls) -> str:
        return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()

    @classmethod
    def set_gemini_model(cls, model_name: str):
        os.environ["GEMINI_MODEL"] = model_name.strip()
        cls._save_key_val("GEMINI_MODEL", model_name.strip())

    # --- Groq (gsk_...) Settings (with backward compatibility) ---
    @classmethod
    def get_groq_api_key(cls) -> str:
        return os.environ.get("GROQ_API_KEY", os.environ.get("GROK_API_KEY", os.environ.get("XAI_API_KEY", ""))).strip()

    @classmethod
    def set_groq_api_key(cls, key: str):
        k = key.strip()
        os.environ["GROQ_API_KEY"] = k
        cls._save_key_val("GROQ_API_KEY", k)
        os.environ["GROK_API_KEY"] = k
        cls._save_key_val("GROK_API_KEY", k)

    @classmethod
    def get_groq_model(cls) -> str:
        val = os.environ.get("GROQ_MODEL", os.environ.get("GROK_MODEL", "qwen/qwen3.8-27b")).strip()
        if "grok" in val.lower() or not val:
            val = "qwen/qwen3.8-27b"
        return val

    @classmethod
    def set_groq_model(cls, model_name: str):
        m = model_name.strip() or "qwen/qwen3.8-27b"
        os.environ["GROQ_MODEL"] = m
        cls._save_key_val("GROQ_MODEL", m)
        os.environ["GROK_MODEL"] = m
        cls._save_key_val("GROK_MODEL", m)

    # Aliases for backwards compatibility
    get_grok_api_key = get_groq_api_key
    set_grok_api_key = set_groq_api_key
    get_grok_model = get_groq_model
    set_grok_model = set_groq_model

    # --- Audio Source Mode: speaker, mic, both ---
    @classmethod
    def get_audio_mode(cls) -> str:
        val = os.environ.get("AUDIO_MODE", "speaker").strip().lower()
        if val not in ("speaker", "mic", "both"):
            val = "speaker"
        return val

    @classmethod
    def set_audio_mode(cls, mode: str):
        val = mode.strip().lower()
        if val not in ("speaker", "mic", "both"):
            val = "speaker"
        os.environ["AUDIO_MODE"] = val
        cls._save_key_val("AUDIO_MODE", val)

    # --- Audio Devices ---
    @classmethod
    def get_speaker_device(cls) -> str:
        return os.environ.get("AUDIO_SPEAKER_DEVICE", os.environ.get("AUDIO_OUTPUT_DEVICE", "")).strip()

    @classmethod
    def set_speaker_device(cls, name: str):
        os.environ["AUDIO_SPEAKER_DEVICE"] = name.strip()
        cls._save_key_val("AUDIO_SPEAKER_DEVICE", name.strip())

    @classmethod
    def get_mic_device(cls) -> str:
        return os.environ.get("AUDIO_MIC_DEVICE", "").strip()

    @classmethod
    def set_mic_device(cls, name: str):
        os.environ["AUDIO_MIC_DEVICE"] = name.strip()
        cls._save_key_val("AUDIO_MIC_DEVICE", name.strip())

    # --- Voice Activity Detection (VAD) ---
    @classmethod
    def get_silence_duration(cls) -> float:
        try:
            return float(os.environ.get("VAD_SILENCE_SECONDS", "1.1"))
        except ValueError:
            return 1.1

    @classmethod
    def set_silence_duration(cls, val: float):
        os.environ["VAD_SILENCE_SECONDS"] = str(round(val, 2))
        cls._save_key_val("VAD_SILENCE_SECONDS", str(round(val, 2)))

    @classmethod
    def get_min_speech_duration(cls) -> float:
        try:
            return float(os.environ.get("VAD_MIN_SPEECH_SECONDS", "0.6"))
        except ValueError:
            return 0.6

    @classmethod
    def set_min_speech_duration(cls, val: float):
        os.environ["VAD_MIN_SPEECH_SECONDS"] = str(round(val, 2))
        cls._save_key_val("VAD_MIN_SPEECH_SECONDS", str(round(val, 2)))

    @classmethod
    def get_energy_threshold(cls) -> float:
        try:
            return float(os.environ.get("VAD_ENERGY_THRESHOLD", "0.008"))
        except ValueError:
            return 0.008

    @classmethod
    def set_energy_threshold(cls, val: float):
        os.environ["VAD_ENERGY_THRESHOLD"] = str(round(val, 4))
        cls._save_key_val("VAD_ENERGY_THRESHOLD", str(round(val, 4)))

    # --- Screen Invisibility / Stealth Mode ---
    @classmethod
    def get_stealth_mode(cls) -> bool:
        val = os.environ.get("STEALTH_MODE", "true").strip().lower()
        return val in ("true", "1", "yes")

    @classmethod
    def set_stealth_mode(cls, enabled: bool):
        val_str = "true" if enabled else "false"
        os.environ["STEALTH_MODE"] = val_str
        cls._save_key_val("STEALTH_MODE", val_str)

    @classmethod
    def _save_key_val(cls, key: str, val: str):
        lines = []
        found = False
        if os.path.exists(cls.ENV_FILE):
            with open(cls.ENV_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
        new_lines = []
        for line in lines:
            if line.strip().startswith(f"{key}="):
                new_lines.append(f"{key}={val}\n")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{key}={val}\n")
        with open(cls.ENV_FILE, "w", encoding="utf-8") as f:
            f.writelines(new_lines)


# ---------------------------------------------------------------------------
# Multilingual System Prompt & Response Parser
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an invisible real-time exam and interview copilot listening to live speech in ANY language (Ukrainian, English, Polish, German, Spanish, French, etc.).
Analyze the incoming audio / speech:
1. If the speech is regular conversation, background chatter, greetings, or filler sentences without a question or test task, reply ONLY with: NO_QUESTION
2. If the speech contains an actual question, task, problem, or test query:
   - CRITICAL RULE: ALWAYS reply in the EXACT SAME LANGUAGE as the question asked!
   - If the speaker asks in Ukrainian, both the question and answer MUST be strictly in Ukrainian.
   - If the speaker asks in English, reply in English.
   - Never default or switch to English when a foreign/different language is spoken.
   - Keep answers direct, 100% accurate, concise, with formulas or code snippets as needed, without pleasantries or filler.
   Reply strictly in this format:
   Q: [Concise question as heard, in its original spoken language]
   A: [Direct, extremely concise, 100% accurate answer, formula, or code snippet without pleasantries, in the EXACT same language as the question]"""


def parse_ai_response(text: str) -> Optional[Tuple[str, str]]:
    """
    Parses the response from Gemini or Grok.
    Returns (question, answer) or None if NO_QUESTION was returned.
    Supports English, Ukrainian, and other multilingual prefixes.
    """
    if not text:
        return None
    raw = text.strip()
    upper_raw = raw.upper()

    # Silently ignore if model signals no actionable query
    if any(neg in upper_raw for neg in ["NO_QUESTION", "НЕМАЄ ПИТАННЯ", "НЕМА ПИТАННЯ", "НЕТ ВОПРОСА"]):
        return None

    q_prefixes = (
        "Q:", "q:", "Question:", "QUESTION:",
        "Питання:", "питання:", "ПИТАННЯ:", "П:", "п:",
        "Вопрос:", "вопрос:", "ВОПРОС:"
    )
    a_prefixes = (
        "A:", "a:", "Answer:", "ANSWER:",
        "Відповідь:", "відповідь:", "ВІДПОВІДЬ:",
        "Ответ:", "ответ:", "ОТВЕТ:",
        "В:", "в:"
    )

    q_lines: List[str] = []
    a_lines: List[str] = []
    mode: Optional[str] = None

    for line in raw.splitlines():
        trimmed = line.strip()
        matched_q = next((p for p in q_prefixes if trimmed.startswith(p)), None)
        matched_a = next((p for p in a_prefixes if trimmed.startswith(p)), None)

        if matched_q:
            mode = "Q"
            q_lines.append(trimmed[len(matched_q):].strip())
        elif matched_a:
            mode = "A"
            a_lines.append(trimmed[len(matched_a):].strip())
        elif mode == "Q":
            q_lines.append(line)
        elif mode == "A":
            a_lines.append(line)
        else:
            a_lines.append(line)

    question = "\n".join(q_lines).strip()
    answer = "\n".join(a_lines).strip()

    if not question and answer:
        question = "Запитання / Question"

    if not answer and not question:
        return None

    return question, answer


# ---------------------------------------------------------------------------
# Background Worker 1: Audio Capture Worker (Speaker, Mic, or Both)
# ---------------------------------------------------------------------------
class AudioCaptureWorker(QThread):
    """
    Continuous audio capture supporting 3 modes:
    1. 'speaker': Speaker Only (Interviewer) - WASAPI loopback from headphones/speakers.
    2. 'mic': Microphone Only (Me) - Physical microphone input.
    3. 'both': Both Speaker and Microphone - Concurrently captures and mixes both in real-time.

    Features real-time VAD (Voice Activity Detection), pre-roll buffer,
    adaptive energy threshold, and zero audio loss.
    """
    audio_level = pyqtSignal(float)                # Real-time RMS volume (0.0 to 1.0)
    audio_segment_ready = pyqtSignal(bytes, float) # (wav_bytes, duration_seconds)
    status_changed = pyqtSignal(str, str)          # (status_message, status_badge_type)
    error_occurred = pyqtSignal(str)               # Error message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self._paused = False
        self._needs_reconnect = False

        self.audio_mode = AppConfig.get_audio_mode()
        self.speaker_device_name = AppConfig.get_speaker_device()
        self.mic_device_name = AppConfig.get_mic_device()
        self.silence_threshold = AppConfig.get_silence_duration()
        self.min_speech_threshold = AppConfig.get_min_speech_duration()
        self.energy_threshold = AppConfig.get_energy_threshold()

    def set_paused(self, paused: bool):
        self._paused = paused
        if paused:
            self.status_changed.emit("Аудіо на паузі", "paused")
        else:
            self._emit_listening_status()

    def set_audio_mode(self, mode: str):
        """Switches between 'speaker', 'mic', 'both'."""
        self.audio_mode = mode
        AppConfig.set_audio_mode(mode)
        self._needs_reconnect = True
        self._emit_listening_status()
        logger.info(f"Audio mode switched to: {mode}")

    def update_settings(self, audio_mode: str, speaker_device: str, mic_device: str,
                        silence_dur: float, min_speech_dur: float, energy_thresh: float):
        self.audio_mode = audio_mode
        self.speaker_device_name = speaker_device
        self.mic_device_name = mic_device
        self.silence_threshold = silence_dur
        self.min_speech_threshold = min_speech_dur
        self.energy_threshold = energy_thresh
        self._needs_reconnect = True

    def stop(self):
        self._running = False
        self._needs_reconnect = True
        self.wait(1500)

    def _emit_listening_status(self):
        mode_labels = {
            "speaker": "Слухаю співрозмовника (Speaker Only)...",
            "mic": "Слухаю мій мікрофон (Microphone Only)...",
            "both": "Слухаю співрозмовника та мікрофон (Both)..."
        }
        self.status_changed.emit(mode_labels.get(self.audio_mode, "Слухаю аудіо..."), "listening")

    def _get_speaker_loopback(self):
        try:
            if self.speaker_device_name:
                for s in sc.all_speakers():
                    if self.speaker_device_name.lower() in s.name.lower():
                        return sc.get_microphone(id=str(s.name), include_loopback=True)
            default_spk = sc.default_speaker()
            return sc.get_microphone(id=str(default_spk.name), include_loopback=True)
        except Exception as e:
            logger.warning(f"Error resolving speaker loopback: {e}")
            return sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True)

    def _get_microphone(self):
        try:
            if self.mic_device_name:
                for m in sc.all_microphones():
                    if not m.isloopback and self.mic_device_name.lower() in m.name.lower():
                        return m
            return sc.default_microphone()
        except Exception as e:
            logger.warning(f"Error resolving microphone: {e}")
            return sc.default_microphone()

    def run(self):
        target_sample_rate = 16000
        chunk_frames = 1600  # 100ms chunks at 16kHz
        chunk_duration = chunk_frames / float(target_sample_rate)

        while self._running:
            self._needs_reconnect = False
            self._emit_listening_status()

            speech_chunks: List[np.ndarray] = []
            pre_roll_chunks: List[np.ndarray] = []
            max_pre_roll = 5  # ~500ms pre-roll to prevent clipping word starts
            is_speech_active = False
            silence_elapsed = 0.0
            noise_floor = self.energy_threshold

            try:
                if self.audio_mode == "speaker":
                    spk_dev = self._get_speaker_loopback()
                    logger.info(f"Recording Speaker Loopback: [{spk_dev.name}]")
                    with spk_dev.recorder(samplerate=target_sample_rate, channels=1) as recorder:
                        while self._running and not self._needs_reconnect:
                            data = recorder.record(numframes=chunk_frames)
                            if data is None or len(data) == 0:
                                continue
                            mono = data[:, 0] if data.ndim > 1 else data
                            is_speech_active, silence_elapsed, noise_floor = self._process_chunk(
                                mono, chunk_duration, speech_chunks, pre_roll_chunks,
                                max_pre_roll, is_speech_active, silence_elapsed,
                                noise_floor, target_sample_rate
                            )

                elif self.audio_mode == "mic":
                    mic_dev = self._get_microphone()
                    logger.info(f"Recording Microphone: [{mic_dev.name}]")
                    with mic_dev.recorder(samplerate=target_sample_rate, channels=1) as recorder:
                        while self._running and not self._needs_reconnect:
                            data = recorder.record(numframes=chunk_frames)
                            if data is None or len(data) == 0:
                                continue
                            mono = data[:, 0] if data.ndim > 1 else data
                            is_speech_active, silence_elapsed, noise_floor = self._process_chunk(
                                mono, chunk_duration, speech_chunks, pre_roll_chunks,
                                max_pre_roll, is_speech_active, silence_elapsed,
                                noise_floor, target_sample_rate
                            )

                elif self.audio_mode == "both":
                    # Dual concurrent capture with real-time mixing
                    spk_dev = self._get_speaker_loopback()
                    mic_dev = self._get_microphone()
                    logger.info(f"Recording Dual (Both): [{spk_dev.name}] + [{mic_dev.name}]")

                    q_spk = queue.Queue(maxsize=15)
                    q_mic = queue.Queue(maxsize=15)
                    stop_dual = threading.Event()

                    def _spk_worker():
                        try:
                            with spk_dev.recorder(samplerate=target_sample_rate, channels=1) as r:
                                while not stop_dual.is_set():
                                    d = r.record(numframes=chunk_frames)
                                    if d is not None and len(d) > 0:
                                        m = d[:, 0] if d.ndim > 1 else d
                                        if q_spk.full():
                                            try: q_spk.get_nowait()
                                            except queue.Empty: pass
                                        q_spk.put(m)
                        except Exception as ex:
                            logger.error(f"Speaker loopback worker error: {ex}")

                    def _mic_worker():
                        try:
                            with mic_dev.recorder(samplerate=target_sample_rate, channels=1) as r:
                                while not stop_dual.is_set():
                                    d = r.record(numframes=chunk_frames)
                                    if d is not None and len(d) > 0:
                                        m = d[:, 0] if d.ndim > 1 else d
                                        if q_mic.full():
                                            try: q_mic.get_nowait()
                                            except queue.Empty: pass
                                        q_mic.put(m)
                        except Exception as ex:
                            logger.error(f"Microphone worker error: {ex}")

                    t_spk = threading.Thread(target=_spk_worker, daemon=True)
                    t_mic = threading.Thread(target=_mic_worker, daemon=True)
                    t_spk.start()
                    t_mic.start()

                    try:
                        while self._running and not self._needs_reconnect:
                            try:
                                s_chunk = q_spk.get(timeout=0.3)
                            except queue.Empty:
                                continue

                            try:
                                m_chunk = q_mic.get_nowait()
                            except queue.Empty:
                                m_chunk = np.zeros_like(s_chunk)

                            # Mix together with clipping safeguard
                            min_len = min(len(s_chunk), len(m_chunk))
                            mixed = np.clip(s_chunk[:min_len] + m_chunk[:min_len], -1.0, 1.0)

                            is_speech_active, silence_elapsed, noise_floor = self._process_chunk(
                                mixed, chunk_duration, speech_chunks, pre_roll_chunks,
                                max_pre_roll, is_speech_active, silence_elapsed,
                                noise_floor, target_sample_rate
                            )
                    finally:
                        stop_dual.set()
                        t_spk.join(timeout=0.4)
                        t_mic.join(timeout=0.4)

            except Exception as e:
                if self._needs_reconnect:
                    continue
                logger.error(f"Audio stream error: {e}")
                self.error_occurred.emit(f"Помилка звуку: {str(e)[:60]}")
                self.status_changed.emit("Перепідключення...", "error")
                time.sleep(1.5)

    def _process_chunk(self, mono: np.ndarray, chunk_duration: float,
                       speech_chunks: List[np.ndarray], pre_roll_chunks: List[np.ndarray],
                       max_pre_roll: int, is_speech_active: bool,
                       silence_elapsed: float, noise_floor: float,
                       target_sample_rate: int) -> Tuple[bool, float, float]:
        """Runs VAD calculations on a single mono audio chunk."""
        rms = float(np.sqrt(np.mean(mono ** 2)))
        norm_level = min(1.0, rms * 25.0)
        self.audio_level.emit(norm_level)

        if self._paused:
            speech_chunks.clear()
            pre_roll_chunks.clear()
            return False, 0.0, noise_floor

        # Adaptive noise floor tracking
        if not is_speech_active:
            noise_floor = min(noise_floor * 0.96 + rms * 0.04, self.energy_threshold)

        active_threshold = max(self.energy_threshold * 0.55, noise_floor * 1.8)
        is_speech_chunk = rms >= active_threshold

        if not is_speech_active:
            # Idle state: buffer pre-roll
            pre_roll_chunks.append(mono)
            if len(pre_roll_chunks) > max_pre_roll:
                pre_roll_chunks.pop(0)

            if is_speech_chunk:
                is_speech_active = True
                silence_elapsed = 0.0
                speech_chunks.clear()
                speech_chunks.extend(pre_roll_chunks)
                speech_chunks.append(mono)
                self.status_changed.emit("Розпізнаю мовлення...", "speaking")
        else:
            # Speech active state
            speech_chunks.append(mono)
            if is_speech_chunk:
                silence_elapsed = 0.0
            else:
                silence_elapsed += chunk_duration

            total_speech_sec = len(speech_chunks) * chunk_duration

            # Complete utterance triggered
            if (silence_elapsed >= self.silence_threshold and total_speech_sec >= self.min_speech_threshold) or (total_speech_sec >= 35.0):
                logger.info(f"Utterance captured: {total_speech_sec:.2f}s (Silence: {silence_elapsed:.2f}s)")
                full_audio = np.concatenate(speech_chunks).astype(np.float32)

                # Encode to 16kHz 16-bit PCM WAV in memory
                bio = io.BytesIO()
                sf.write(bio, full_audio, target_sample_rate, format="WAV", subtype="PCM_16")
                bio.seek(0)
                wav_bytes = bio.read()

                self.audio_segment_ready.emit(wav_bytes, total_speech_sec)

                speech_chunks.clear()
                pre_roll_chunks.clear()
                is_speech_active = False
                silence_elapsed = 0.0
                self._emit_listening_status()

        return is_speech_active, silence_elapsed, noise_floor


# ---------------------------------------------------------------------------
# Background Worker 2: Multimodal AI Processing Thread (Gemini & Groq)
# ---------------------------------------------------------------------------
class AIWorker(QThread):
    """
    Pulls audio segments from a thread-safe queue and queries either:
    1. Google Gemini (multimodal audio directly via google-genai SDK).
    2. Groq (speech-to-text via whisper-large-v3-turbo, then chat completion via openai SDK on https://api.groq.com/openai/v1).
    Emits question, answer, latency, and provider name cleanly to UI.
    """
    answer_received = pyqtSignal(str, str, float, str)  # (question, answer, latency, provider_name)
    status_changed = pyqtSignal(str, str)               # (status_message, status_badge_type)
    error_occurred = pyqtSignal(str)                    # Error message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self._queue = queue.Queue()

        self.provider = AppConfig.get_ai_provider()
        self.gemini_key = AppConfig.get_gemini_api_key()
        self.gemini_model = AppConfig.get_gemini_model()
        self.groq_key = AppConfig.get_groq_api_key()
        self.groq_model = AppConfig.get_groq_model()

        self._gemini_client = None
        self._groq_client = None
        self._init_clients()

    def _init_clients(self):
        # 1. Init Gemini
        if self.gemini_key:
            try:
                from google import genai
                self._gemini_client = genai.Client(api_key=self.gemini_key)
                logger.info(f"Gemini client initialized with model: {self.gemini_model}")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini client: {e}")
                self._gemini_client = None
        else:
            self._gemini_client = None

        # 2. Init Groq (OpenAI client with base_url="https://api.groq.com/openai/v1")
        if self.groq_key:
            try:
                from openai import OpenAI
                self._groq_client = OpenAI(
                    api_key=self.groq_key,
                    base_url="https://api.groq.com/openai/v1"
                )
                logger.info(f"Groq client initialized with model: {self.groq_model}")
            except Exception as e:
                logger.error(f"Failed to initialize Groq client: {e}")
                self._groq_client = None
        else:
            self._groq_client = None

    def update_credentials(self, provider: str, gemini_key: str, gemini_model: str,
                           groq_key: str = "", groq_model: str = "",
                           grok_key: str = "", grok_model: str = ""):
        prov = provider.strip().lower()
        if prov in ("grok", "xai"):
            prov = "groq"
        self.provider = prov
        self.gemini_key = gemini_key.strip()
        self.gemini_model = gemini_model.strip()
        self.groq_key = (groq_key or grok_key).strip()
        self.groq_model = (groq_model or grok_model).strip() or "qwen/qwen3.8-27b"
        self._init_clients()

    def enqueue_audio(self, audio_bytes: bytes, duration: float, mime_type: str = "audio/wav"):
        self._queue.put((audio_bytes, duration, mime_type))

    def stop(self):
        self._running = False
        self._queue.put((None, 0.0, "audio/wav"))
        self.wait(1500)

    def run(self):
        while self._running:
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is None:
                continue
            audio_bytes, audio_duration, mime_type = item
            if audio_bytes is None:
                break

            start_time = time.time()

            # -------------------------------------------------------
            # Provider: Google Gemini
            # -------------------------------------------------------
            if self.provider == "gemini":
                if not self.gemini_key or self._gemini_client is None:
                    self.error_occurred.emit("Gemini API Key missing. Open ⚙ Settings to add key.")
                    self.status_changed.emit("API Key Missing", "error")
                    continue

                self.status_changed.emit("Gemini аналізує запитання...", "processing")
                try:
                    from google.genai import types

                    response = self._gemini_client.models.generate_content(
                        model=self.gemini_model,
                        contents=[
                            types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                            "Analyze this speech segment in whatever language is spoken (e.g. Ukrainian, English, etc.). If a question or test query is present, answer it accurately and strictly in the EXACT same language as the speaker."
                        ],
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_PROMPT,
                            temperature=0.1,
                        )
                    )

                    latency = round(time.time() - start_time, 2)
                    raw_text = response.text or ""
                    logger.info(f"Gemini Response ({latency}s):\n{raw_text[:120]}...")

                    parsed = parse_ai_response(raw_text)
                    if parsed is not None:
                        q_text, a_text = parsed
                        self.answer_received.emit(q_text, a_text, latency, f"Gemini ({self.gemini_model})")
                        self.status_changed.emit("Запитання розпізнано", "success")
                    else:
                        logger.info("Conversational audio — no question asked.")
                        self.status_changed.emit("Слухаю...", "listening")

                except Exception as e:
                    err_str = str(e)
                    logger.error(f"Gemini API error: {err_str}")
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        self.error_occurred.emit("Gemini Rate limit (429). Wait a moment.")
                    elif "400" in err_str or "API_KEY_INVALID" in err_str:
                        self.error_occurred.emit("Invalid Gemini API Key! Check ⚙ Settings.")
                    else:
                        self.error_occurred.emit(f"Gemini Error: {err_str[:60]}")
                    self.status_changed.emit("Готово", "listening")

            # -------------------------------------------------------
            # Provider: Groq (Ultra-Fast LPU Inference)
            # -------------------------------------------------------
            elif self.provider in ("groq", "grok"):
                if not self.groq_key or self._groq_client is None:
                    self.error_occurred.emit("Groq API Key (gsk_...) missing. Відкрийте ⚙ Налаштування.")
                    self.status_changed.emit("Groq Key Missing", "error")
                    continue

                self.status_changed.emit("Groq розпізнає мову...", "processing")
                try:
                    # 1. Native Groq Whisper Speech-to-Text (<200ms)
                    transcript_text = ""
                    try:
                        bio = io.BytesIO(audio_bytes)
                        bio.name = "audio.wav"
                        stt_res = self._groq_client.audio.transcriptions.create(
                            model="whisper-large-v3-turbo",
                            file=bio
                        )
                        transcript_text = getattr(stt_res, "text", str(stt_res)).strip()
                    except Exception as stt_err:
                        logger.warning(f"Groq whisper-large-v3-turbo failed: {stt_err}")
                        try:
                            bio2 = io.BytesIO(audio_bytes)
                            bio2.name = "audio.wav"
                            stt_res2 = self._groq_client.audio.transcriptions.create(
                                model="whisper-large-v3",
                                file=bio2
                            )
                            transcript_text = getattr(stt_res2, "text", str(stt_res2)).strip()
                        except Exception as stt_err2:
                            logger.warning(f"Groq whisper-large-v3 failed: {stt_err2}")

                    # Fallback to Gemini for STT if Gemini key available and Groq STT failed
                    if not transcript_text and self._gemini_client:
                        try:
                            from google.genai import types
                            stt_gem = self._gemini_client.models.generate_content(
                                model="gemini-2.5-flash",
                                contents=[
                                    types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                                    "Transcribe the spoken audio verbatim in its original language. Reply ONLY with the transcription text."
                                ]
                            )
                            transcript_text = (stt_gem.text or "").strip()
                        except Exception:
                            pass

                    if not transcript_text:
                        logger.info("No speech recognized in audio segment.")
                        self.status_changed.emit("Слухаю...", "listening")
                        continue

                    self.status_changed.emit("Groq генерує відповідь...", "processing")

                    # 2. Query Groq Chat Completions (LPU high-speed inference)
                    completion = self._groq_client.chat.completions.create(
                        model=self.groq_model,
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": f"User speech:\n{transcript_text}"}
                        ],
                        temperature=0.1,
                        max_tokens=600
                    )

                    latency = round(time.time() - start_time, 2)
                    raw_text = completion.choices[0].message.content or ""
                    logger.info(f"Groq Response ({latency}s):\n{raw_text[:120]}...")

                    parsed = parse_ai_response(raw_text)
                    if parsed is not None:
                        q_text, a_text = parsed
                        self.answer_received.emit(q_text, a_text, latency, f"Groq ({self.groq_model})")
                        self.status_changed.emit("Запитання розпізнано", "success")
                    else:
                        logger.info("Conversational audio — no question asked.")
                        self.status_changed.emit("Слухаю...", "listening")

                except Exception as e:
                    err_str = str(e)
                    logger.error(f"Groq API error: {err_str}")
                    if "401" in err_str or "invalid_api_key" in err_str or "Incorrect API key" in err_str:
                        self.error_occurred.emit("Невірний Groq API Key (gsk_...)! Перевірте ⚙ Налаштування.")
                    elif "429" in err_str:
                        self.error_occurred.emit("Groq Rate limit reached (429). Зачекайте хвилинку.")
                    elif "404" in err_str or "model_not_found" in err_str:
                        self.error_occurred.emit(f"Модель '{self.groq_model}' недоступна в Groq. Оберіть qwen/qwen3.8-27b.")
                    else:
                        self.error_occurred.emit(f"Groq Помилка: {err_str[:60]}")
                    self.status_changed.emit("Готово", "listening")


# ---------------------------------------------------------------------------
# UI Component: Sleek Status Badge Pill (v1 Style)
# ---------------------------------------------------------------------------
class StatusPill(QFrame):
    """Modern translucent glowing status indicator pill."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(26)
        self.setStyleSheet("""
            QFrame {
                background-color: rgba(26, 31, 46, 0.85);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 13px;
                padding: 0 10px;
            }
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 8, 0)
        layout.setSpacing(6)

        self.dot = QLabel("●")
        self.dot.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self.dot.setStyleSheet("color: #10b981;")
        layout.addWidget(self.dot)

        self.text_label = QLabel("LISTENING")
        self.text_label.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self.text_label.setStyleSheet("color: #e2e8f0; letter-spacing: 0.5px;")
        layout.addWidget(self.text_label)

    def set_status(self, text: str, badge_type: str = "listening"):
        color_map = {
            "listening": ("#10b981", "#10b981", "LISTENING"),
            "speaking": ("#38bdf8", "#38bdf8", "SPEECH DETECTED"),
            "processing": ("#f59e0b", "#f59e0b", "AI THINKING..."),
            "success": ("#34d399", "#34d399", "ANSWERED"),
            "paused": ("#94a3b8", "#94a3b8", "PAUSED"),
            "error": ("#ef4444", "#ef4444", "ATTENTION"),
        }
        dot_color, text_color, default_label = color_map.get(badge_type, ("#10b981", "#e2e8f0", text.upper()))
        display_text = text if badge_type in ["error", "processing"] else default_label
        self.dot.setStyleSheet(f"color: {dot_color};")
        self.text_label.setStyleSheet(f"color: {text_color}; letter-spacing: 0.5px;")
        self.text_label.setText(display_text)


# ---------------------------------------------------------------------------
# UI Component: Mini Real-time Equalizer Visualizer (v1 Style)
# ---------------------------------------------------------------------------
class MiniAudioVisualizer(QWidget):
    """Dynamic 5-bar mini equalizer that reacts to audio in real-time."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(46, 18)
        self._level = 0.0
        self._bars = [0.1, 0.1, 0.1, 0.1, 0.1]
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate_decay)
        self._timer.start(40)

    def set_level(self, level: float):
        self._level = max(0.0, min(1.0, level))
        for i in range(5):
            mult = 0.6 + 0.4 * math.sin(i * 1.3 + time.time() * 8.0)
            target = max(0.08, self._level * mult)
            self._bars[i] = max(self._bars[i], target)
        self.update()

    def _animate_decay(self):
        changed = False
        for i in range(5):
            if self._bars[i] > 0.08:
                self._bars[i] = max(0.08, self._bars[i] * 0.82)
                changed = True
        if changed:
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bar_width = 5
        gap = 4
        h = self.height()

        for i, val in enumerate(self._bars):
            bar_h = max(3.0, val * (h - 2))
            x = i * (bar_width + gap)
            y = h - bar_h

            if val > 0.6:
                color = QColor(245, 158, 11, 230)
            elif val > 0.2:
                color = QColor(56, 189, 248, 220)
            else:
                color = QColor(16, 185, 129, 180)

            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(int(x), int(y), int(bar_width), int(bar_h), 2.0, 2.0)


# ---------------------------------------------------------------------------
# UI Component: Q&A Chat Message Card (v1 Style)
# ---------------------------------------------------------------------------
class MessageCard(QFrame):
    """Sleek message card showing question & answer with copy-to-clipboard."""
    def __init__(self, question: str, answer: str, latency: float = 0.0,
                 provider_label: str = "", parent=None):
        super().__init__(parent)
        self.question = question
        self.answer = answer
        self.latency = latency

        self.setStyleSheet("""
            MessageCard {
                background-color: rgba(22, 27, 38, 0.90);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
            }
        """)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        # 1. Header (Timestamp, Model, Latency, Copy)
        header = QHBoxLayout()
        header.setSpacing(8)

        now_str = datetime.now().strftime("%H:%M:%S")
        ts_label = QLabel(f"⏱ {now_str}")
        ts_label.setFont(QFont("Segoe UI", 8))
        ts_label.setStyleSheet("color: #64748b;")
        header.addWidget(ts_label)

        if provider_label:
            p_label = QLabel(f"🤖 {provider_label}")
            p_label.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
            p_label.setStyleSheet("color: #a78bfa;")
            header.addWidget(p_label)

        if latency > 0:
            lat_label = QLabel(f"⚡ {latency}s")
            lat_label.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            lat_label.setStyleSheet("color: #38bdf8;")
            header.addWidget(lat_label)

        header.addStretch()

        self.copy_btn = QPushButton("📋 Copy Answer")
        self.copy_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.copy_btn.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self.copy_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.06);
                color: #94a3b8;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 3px 8px;
            }
            QPushButton:hover {
                background: rgba(56, 189, 248, 0.2);
                color: #38bdf8;
                border: 1px solid #38bdf8;
            }
        """)
        self.copy_btn.clicked.connect(self._copy_answer)
        header.addWidget(self.copy_btn)

        layout.addLayout(header)

        # 2. Question section
        q_frame = QFrame()
        q_frame.setStyleSheet("""
            QFrame {
                background: rgba(14, 165, 233, 0.08);
                border-left: 3px solid #38bdf8;
                border-radius: 4px;
                padding: 6px 10px;
            }
        """)
        q_layout = QVBoxLayout(q_frame)
        q_layout.setContentsMargins(4, 2, 4, 2)
        q_layout.setSpacing(3)

        q_badge = QLabel("QUESTION")
        q_badge.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        q_badge.setStyleSheet("color: #38bdf8; letter-spacing: 0.8px;")
        q_layout.addWidget(q_badge)

        q_content = QLabel(question)
        q_content.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        q_content.setStyleSheet("color: #f1f5f9;")
        q_content.setWordWrap(True)
        q_content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        q_layout.addWidget(q_content)

        layout.addWidget(q_frame)

        # 3. Answer section
        a_frame = QFrame()
        a_frame.setStyleSheet("""
            QFrame {
                background: rgba(16, 185, 129, 0.08);
                border-left: 3px solid #10b981;
                border-radius: 4px;
                padding: 6px 10px;
            }
        """)
        a_layout = QVBoxLayout(a_frame)
        a_layout.setContentsMargins(4, 2, 4, 2)
        a_layout.setSpacing(4)

        a_badge = QLabel("AI ANSWER")
        a_badge.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        a_badge.setStyleSheet("color: #10b981; letter-spacing: 0.8px;")
        a_layout.addWidget(a_badge)

        a_content = QLabel(answer)
        a_content.setFont(QFont("Segoe UI", 10))
        a_content.setStyleSheet("color: #e2e8f0; line-height: 1.4;")
        a_content.setTextFormat(Qt.TextFormat.MarkdownText)
        a_content.setWordWrap(True)
        a_content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        a_layout.addWidget(a_content)

        layout.addWidget(a_frame)

    def _copy_answer(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.answer)
        self.copy_btn.setText("✓ Copied!")
        self.copy_btn.setStyleSheet("""
            QPushButton {
                background: rgba(16, 185, 129, 0.25);
                color: #34d399;
                border: 1px solid #10b981;
                border-radius: 6px;
                padding: 3px 8px;
            }
        """)
        QTimer.singleShot(1800, self._reset_copy_btn)

    def _reset_copy_btn(self):
        self.copy_btn.setText("📋 Copy Answer")
        self.copy_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.06);
                color: #94a3b8;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 3px 8px;
            }
            QPushButton:hover {
                background: rgba(56, 189, 248, 0.2);
                color: #38bdf8;
                border: 1px solid #38bdf8;
            }
        """)


def style_combobox(combo: QComboBox):
    """
    Applies clean dark theme styling to QComboBox and explicitly forces
    its popup view (QListView) to dark mode to prevent Windows white-out bug.
    """
    combo.setStyleSheet("""
        QComboBox {
            background-color: #1e222b;
            border: 1px solid rgba(255, 255, 255, 0.14);
            border-radius: 6px;
            padding: 6px 10px;
            padding-right: 28px;
            color: #f8fafc;
            font-family: 'Segoe UI';
            font-size: 12px;
            font-weight: 500;
        }
        QComboBox:hover {
            border: 1px solid rgba(56, 189, 248, 0.5);
            background-color: #242935;
        }
        QComboBox:focus {
            border: 1px solid #38bdf8;
            background-color: #242935;
        }
        QComboBox QLineEdit {
            color: #f8fafc;
            background: transparent;
            border: none;
            padding: 0;
            font-family: 'Segoe UI';
            font-size: 12px;
        }
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 24px;
            border-left: 1px solid rgba(255, 255, 255, 0.1);
        }
        QComboBox::down-arrow {
            width: 0;
            height: 0;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid #94a3b8;
        }
    """)
    view = combo.view()
    if view:
        view.setStyleSheet("""
            QListView {
                background-color: #1e222b;
                color: #f8fafc;
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 6px;
                padding: 4px;
                selection-background-color: #0078d4;
                selection-color: #ffffff;
                outline: none;
                font-family: 'Segoe UI';
                font-size: 12px;
            }
            QListView::item {
                color: #f8fafc;
                background-color: transparent;
                padding: 6px 10px;
                border-radius: 4px;
                min-height: 22px;
            }
            QListView::item:hover {
                background-color: rgba(56, 189, 248, 0.2);
                color: #ffffff;
            }
            QListView::item:selected {
                background-color: #0078d4;
                color: #ffffff;
            }
        """)


# ---------------------------------------------------------------------------
# UI Component: Settings Modal Dialog
# ---------------------------------------------------------------------------
class SettingsDialog(QDialog):
    """
    Settings dialog allowing AI provider choice (Google Gemini / xAI Grok),
    API key entries, audio source selection, and VAD sensitivity sliders.
    Protected by WDA_EXCLUDEFROMCAPTURE so it remains invisible during screen sharing.
    """
    settings_saved = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ghost Pilot Settings")
        self.setMinimumSize(480, 560)
        self.resize(520, 640)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._drag_pos = None

        self._build_ui()
        self._load_current_values()

    def showEvent(self, event):
        super().showEvent(event)
        apply_capture_exclusion(int(self.winId()), AppConfig.get_stealth_mode())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)

        container = QFrame()
        container.setObjectName("SettingsContainer")
        container.setStyleSheet("""
            QFrame#SettingsContainer {
                background-color: #0d111a;
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 14px;
            }
            QLabel {
                color: #e2e8f0;
                font-family: 'Segoe UI';
            }
            QFrame.SectionCard {
                background-color: rgba(22, 27, 38, 0.85);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
            }
            QLineEdit {
                background: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 6px;
                padding: 6px 10px;
                color: #f8fafc;
                font-family: 'Segoe UI';
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #38bdf8;
                background: rgba(56, 189, 248, 0.08);
            }
            QComboBox {
                background: #1e222b;
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 6px;
                padding: 6px 10px;
                padding-right: 28px;
                color: #f8fafc;
                font-family: 'Segoe UI';
                font-size: 12px;
            }
            QComboBox:hover {
                border: 1px solid rgba(56, 189, 248, 0.4);
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border-left: 1px solid rgba(255, 255, 255, 0.1);
            }
            QComboBox QAbstractItemView {
                background-color: #22252a;
                color: #f8fafc;
                selection-background-color: #0078d4;
                selection-color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 6px;
                padding: 4px;
                outline: none;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: rgba(255, 255, 255, 0.12);
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #0284c7;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #38bdf8;
                border: 2px solid #0d111a;
                width: 16px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 8px;
            }
            QSlider::handle:horizontal:hover {
                background: #7dd3fc;
            }
        """)

        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(16, 14, 16, 14)
        container_layout.setSpacing(10)

        # 1. Header Bar
        hdr_layout = QHBoxLayout()
        hdr_layout.setSpacing(8)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("⚙ Налаштування Ghost Pilot")
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        title.setStyleSheet("color: #f8fafc;")
        title_box.addWidget(title)

        subtitle = QLabel("AI провайдер, API ключі, джерела звуку та чутливість")
        subtitle.setFont(QFont("Segoe UI", 8))
        subtitle.setStyleSheet("color: #64748b;")
        title_box.addWidget(subtitle)
        hdr_layout.addLayout(title_box)

        hdr_layout.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.05);
                color: #94a3b8;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(244, 63, 94, 0.2);
                color: #f43f5e;
                border: 1px solid #f43f5e;
            }
        """)
        close_btn.clicked.connect(self.reject)
        hdr_layout.addWidget(close_btn)
        container_layout.addLayout(hdr_layout)

        # 2. Scroll Area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: rgba(255, 255, 255, 0.03);
                width: 6px;
                margin: 0;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.18);
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(56, 189, 248, 0.5);
            }
        """)

        content_widget = QWidget()
        content_widget.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 4, 6, 4)
        content_layout.setSpacing(10)

        # --- Card 1: AI Provider & Credentials ---
        card_ai = QFrame()
        card_ai.setProperty("class", "SectionCard")
        card_ai_layout = QVBoxLayout(card_ai)
        card_ai_layout.setContentsMargins(12, 10, 12, 12)
        card_ai_layout.setSpacing(8)

        lbl_sec_ai = QLabel("🤖 ШТУЧНИЙ ІНТЕЛЕКТ (AI ENGINE)")
        lbl_sec_ai.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        lbl_sec_ai.setStyleSheet("color: #38bdf8; letter-spacing: 0.5px;")
        card_ai_layout.addWidget(lbl_sec_ai)

        lbl_prov = QLabel("Активний AI Провайдер:")
        lbl_prov.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        card_ai_layout.addWidget(lbl_prov)

        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Google Gemini (Multimodal)", "gemini")
        self.provider_combo.addItem("Groq (LPU Ultra-Fast gsk_...)", "groq")
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        style_combobox(self.provider_combo)
        card_ai_layout.addWidget(self.provider_combo)

        # Gemini Section
        self.gemini_box = QWidget()
        g_layout = QVBoxLayout(self.gemini_box)
        g_layout.setContentsMargins(0, 0, 0, 0)
        g_layout.setSpacing(6)

        lbl_g_key = QLabel("Gemini API Key:")
        lbl_g_key.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        g_layout.addWidget(lbl_g_key)

        g_key_layout = QHBoxLayout()
        self.gemini_key_input = QLineEdit()
        self.gemini_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_key_input.setPlaceholderText("Ключ Google AI Studio...")
        g_key_layout.addWidget(self.gemini_key_input)

        self.gemini_eye_btn = QPushButton("👁")
        self.gemini_eye_btn.setFixedSize(32, 30)
        self.gemini_eye_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.gemini_eye_btn.clicked.connect(lambda: self._toggle_eye(self.gemini_key_input, self.gemini_eye_btn))
        g_key_layout.addWidget(self.gemini_eye_btn)
        g_layout.addLayout(g_key_layout)

        lbl_g_mod = QLabel("Модель Gemini:")
        lbl_g_mod.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        g_layout.addWidget(lbl_g_mod)

        self.gemini_model_combo = QComboBox()
        self.gemini_model_combo.setEditable(True)
        self.gemini_model_combo.addItems([
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-3.8-flash",
            "gemini-3.5-flash-lite",
            "gemini-1.5-flash"
        ])
        style_combobox(self.gemini_model_combo)
        g_layout.addWidget(self.gemini_model_combo)
        card_ai_layout.addWidget(self.gemini_box)

        # Groq Section (Fast LPU Inference)
        self.grok_box = QWidget()
        gr_layout = QVBoxLayout(self.grok_box)
        gr_layout.setContentsMargins(0, 0, 0, 0)
        gr_layout.setSpacing(6)

        lbl_gr_key = QLabel("Groq API Key (gsk_...):")
        lbl_gr_key.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        gr_layout.addWidget(lbl_gr_key)

        gr_key_layout = QHBoxLayout()
        self.grok_key_input = QLineEdit()
        self.grok_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.grok_key_input.setPlaceholderText("Ключ console.groq.com (починається на gsk_...)...")
        gr_key_layout.addWidget(self.grok_key_input)

        self.grok_eye_btn = QPushButton("👁")
        self.grok_eye_btn.setFixedSize(32, 30)
        self.grok_eye_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.grok_eye_btn.clicked.connect(lambda: self._toggle_eye(self.grok_key_input, self.grok_eye_btn))
        gr_key_layout.addWidget(self.grok_eye_btn)
        gr_layout.addLayout(gr_key_layout)

        lbl_gr_mod = QLabel("Модель Groq:")
        lbl_gr_mod.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        gr_layout.addWidget(lbl_gr_mod)

        self.grok_model_combo = QComboBox()
        self.grok_model_combo.setEditable(True)
        self.grok_model_combo.addItems([
            "qwen/qwen3.8-27b",
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant"
        ])
        style_combobox(self.grok_model_combo)
        gr_layout.addWidget(self.grok_model_combo)
        card_ai_layout.addWidget(self.grok_box)

        content_layout.addWidget(card_ai)

        # --- Card 2: Audio Source Configuration ---
        card_audio = QFrame()
        card_audio.setProperty("class", "SectionCard")
        card_audio_layout = QVBoxLayout(card_audio)
        card_audio_layout.setContentsMargins(12, 10, 12, 12)
        card_audio_layout.setSpacing(8)

        lbl_sec_audio = QLabel("🎧 ДЖЕРЕЛО ЗВУКУ (AUDIO SOURCE)")
        lbl_sec_audio.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        lbl_sec_audio.setStyleSheet("color: #a855f7; letter-spacing: 0.5px;")
        card_audio_layout.addWidget(lbl_sec_audio)

        lbl_audio_mode = QLabel("Режим прослуховування:")
        lbl_audio_mode.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        card_audio_layout.addWidget(lbl_audio_mode)

        self.audio_mode_combo = QComboBox()
        self.audio_mode_combo.addItem("Speaker Only (Interviewer)", "speaker")
        self.audio_mode_combo.addItem("Microphone Only (Me)", "mic")
        self.audio_mode_combo.addItem("Both Speaker and Microphone", "both")
        style_combobox(self.audio_mode_combo)
        card_audio_layout.addWidget(self.audio_mode_combo)

        lbl_spk = QLabel("Динаміки / навушники (Loopback):")
        lbl_spk.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        card_audio_layout.addWidget(lbl_spk)

        self.speaker_combo = QComboBox()
        style_combobox(self.speaker_combo)
        card_audio_layout.addWidget(self.speaker_combo)

        lbl_mic = QLabel("Фізичний мікрофон:")
        lbl_mic.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        card_audio_layout.addWidget(lbl_mic)

        self.mic_combo = QComboBox()
        style_combobox(self.mic_combo)
        card_audio_layout.addWidget(self.mic_combo)

        content_layout.addWidget(card_audio)

        # --- Card 3: Voice Activity Detection (VAD) ---
        card_vad = QFrame()
        card_vad.setProperty("class", "SectionCard")
        card_vad_layout = QVBoxLayout(card_vad)
        card_vad_layout.setContentsMargins(12, 10, 12, 12)
        card_vad_layout.setSpacing(8)

        lbl_sec_vad = QLabel("🎚️ ЧУТЛИВІСТЬ РОЗПІЗНАВАННЯ (VAD)")
        lbl_sec_vad.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        lbl_sec_vad.setStyleSheet("color: #10b981; letter-spacing: 0.5px;")
        card_vad_layout.addWidget(lbl_sec_vad)

        self.energy_label = QLabel("Поріг гучності (чутливість): 0.008")
        self.energy_label.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        card_vad_layout.addWidget(self.energy_label)

        self.energy_slider = QSlider(Qt.Orientation.Horizontal)
        self.energy_slider.setRange(3, 30)
        self.energy_slider.setValue(8)
        self.energy_slider.valueChanged.connect(
            lambda v: self.energy_label.setText(f"Поріг гучності (чутливість): {v/1000.0:.3f}")
        )
        card_vad_layout.addWidget(self.energy_slider)

        self.silence_label = QLabel("Пауза завершення фрази: 1.1s")
        self.silence_label.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        card_vad_layout.addWidget(self.silence_label)

        self.silence_slider = QSlider(Qt.Orientation.Horizontal)
        self.silence_slider.setRange(8, 25)
        self.silence_slider.setValue(11)
        self.silence_slider.valueChanged.connect(
            lambda v: self.silence_label.setText(f"Пауза завершення фрази: {v/10.0:.1f}s")
        )
        card_vad_layout.addWidget(self.silence_slider)

        self.min_speech_label = QLabel("Мін. тривалість фрази: 0.6s")
        self.min_speech_label.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        card_vad_layout.addWidget(self.min_speech_label)

        self.min_speech_slider = QSlider(Qt.Orientation.Horizontal)
        self.min_speech_slider.setRange(4, 25)
        self.min_speech_slider.setValue(6)
        self.min_speech_slider.valueChanged.connect(
            lambda v: self.min_speech_label.setText(f"Мін. тривалість фрази: {v/10.0:.1f}s")
        )
        card_vad_layout.addWidget(self.min_speech_slider)
        content_layout.addWidget(card_vad)

        # --- Card 4: Screen Invisibility / Stealth Mode ---
        card_stealth = QFrame()
        card_stealth.setProperty("class", "SectionCard")
        card_stealth_layout = QVBoxLayout(card_stealth)
        card_stealth_layout.setContentsMargins(12, 10, 12, 12)
        card_stealth_layout.setSpacing(8)

        lbl_sec_stealth = QLabel("🛡️ ВИДИМІСТЬ ВІКНА (SCREEN CAPTURE INVISIBILITY)")
        lbl_sec_stealth.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        lbl_sec_stealth.setStyleSheet("color: #38bdf8; letter-spacing: 0.5px;")
        card_stealth_layout.addWidget(lbl_sec_stealth)

        lbl_st = QLabel("Режим невидимості для демонстрації та скріншотів:")
        lbl_st.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        card_stealth_layout.addWidget(lbl_st)

        self.stealth_combo = QComboBox()
        self.stealth_combo.addItem("👻 Невидимий (приховано від скріншотів, Zoom, Discord, Meet)", True)
        self.stealth_combo.addItem("📷 Видимий (дозволити скріншоти та запис екрана)", False)
        style_combobox(self.stealth_combo)
        card_stealth_layout.addWidget(self.stealth_combo)

        desc_st = QLabel("Виберіть «Видимий», якщо вам потрібно робити скріншоти вікна застосунку або транслювати його.")
        desc_st.setFont(QFont("Segoe UI", 8))
        desc_st.setStyleSheet("color: #94a3b8;")
        desc_st.setWordWrap(True)
        card_stealth_layout.addWidget(desc_st)

        content_layout.addWidget(card_stealth)

        scroll_area.setWidget(content_widget)
        container_layout.addWidget(scroll_area)

        # 3. Footer Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        test_btn = QPushButton("🔑 Test API Key")
        test_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        test_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        test_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                color: #cbd5e1;
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 8px;
                padding: 8px 14px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.16);
                color: #ffffff;
            }
        """)
        test_btn.clicked.connect(self._test_api_key)
        btn_layout.addWidget(test_btn)

        save_btn = QPushButton("💾 Зберегти та застосувати")
        save_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        save_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        save_btn.setStyleSheet("""
            QPushButton {
                background: #0284c7;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 8px 18px;
            }
            QPushButton:hover {
                background: #0369a1;
            }
        """)
        save_btn.clicked.connect(self._save_and_apply)
        btn_layout.addWidget(save_btn)

        container_layout.addLayout(btn_layout)
        root_layout.addWidget(container)

    def _toggle_eye(self, line_edit: QLineEdit, btn: QPushButton):
        if line_edit.echoMode() == QLineEdit.EchoMode.Password:
            line_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            btn.setText("🔒")
        else:
            line_edit.setEchoMode(QLineEdit.EchoMode.Password)
            btn.setText("👁")

    def _on_provider_changed(self):
        prov = self.provider_combo.currentData()
        if prov == "gemini":
            self.gemini_box.show()
            self.grok_box.hide()
        else:
            self.gemini_box.hide()
            self.grok_box.show()

    def _repopulate_devices(self):
        self.speaker_combo.clear()
        self.speaker_combo.addItem("Динаміки/навушники за замовчуванням (Default Output)", "")
        try:
            for spk in sc.all_speakers():
                self.speaker_combo.addItem(f"{spk.name}", spk.name)
        except Exception as e:
            logger.warning(f"Error enumerating speakers: {e}")

        self.mic_combo.clear()
        self.mic_combo.addItem("Мікрофон за замовчуванням (Default Microphone)", "")
        try:
            for mic in sc.all_microphones():
                if not mic.isloopback:
                    self.mic_combo.addItem(f"{mic.name}", mic.name)
        except Exception as e:
            logger.warning(f"Error enumerating microphones: {e}")

    def _load_current_values(self):
        # Provider
        prov = AppConfig.get_ai_provider()
        idx_p = self.provider_combo.findData(prov)
        if idx_p < 0 and prov in ("grok", "xai"):
            idx_p = self.provider_combo.findData("groq")
        if idx_p >= 0:
            self.provider_combo.setCurrentIndex(idx_p)
        self._on_provider_changed()

        # Gemini
        self.gemini_key_input.setText(AppConfig.get_gemini_api_key())
        cur_g_mod = AppConfig.get_gemini_model()
        idx_gm = self.gemini_model_combo.findText(cur_g_mod)
        if idx_gm >= 0:
            self.gemini_model_combo.setCurrentIndex(idx_gm)
        else:
            self.gemini_model_combo.setCurrentText(cur_g_mod)

        # Groq
        self.grok_key_input.setText(AppConfig.get_groq_api_key())
        cur_gr_mod = AppConfig.get_groq_model()
        idx_grm = self.grok_model_combo.findText(cur_gr_mod)
        if idx_grm >= 0:
            self.grok_model_combo.setCurrentIndex(idx_grm)
        else:
            self.grok_model_combo.setCurrentText(cur_gr_mod)

        # Audio Mode
        cur_mode = AppConfig.get_audio_mode()
        idx_am = self.audio_mode_combo.findData(cur_mode)
        if idx_am >= 0:
            self.audio_mode_combo.setCurrentIndex(idx_am)

        # Devices
        self._repopulate_devices()
        spk_dev = AppConfig.get_speaker_device()
        for i in range(self.speaker_combo.count()):
            if self.speaker_combo.itemData(i) == spk_dev:
                self.speaker_combo.setCurrentIndex(i)
                break

        mic_dev = AppConfig.get_mic_device()
        for i in range(self.mic_combo.count()):
            if self.mic_combo.itemData(i) == mic_dev:
                self.mic_combo.setCurrentIndex(i)
                break

        # VAD
        energy_v = int(AppConfig.get_energy_threshold() * 1000)
        self.energy_slider.setValue(max(3, min(30, energy_v)))

        silence_v = int(AppConfig.get_silence_duration() * 10)
        self.silence_slider.setValue(silence_v)

        min_speech_v = int(AppConfig.get_min_speech_duration() * 10)
        self.min_speech_slider.setValue(min_speech_v)

        # Stealth Mode
        cur_stealth = AppConfig.get_stealth_mode()
        idx_st = self.stealth_combo.findData(cur_stealth)
        if idx_st >= 0:
            self.stealth_combo.setCurrentIndex(idx_st)

    def _test_api_key(self):
        prov = self.provider_combo.currentData()
        if prov == "gemini":
            key = self.gemini_key_input.text().strip()
            model = self.gemini_model_combo.currentText().strip()
            if not key:
                QMessageBox.warning(self, "API Key Missing", "Введіть Gemini API Key для перевірки.")
                return
            try:
                from google import genai
                client = genai.Client(api_key=key)
                resp = client.models.generate_content(
                    model=model,
                    contents="Reply with 'OK'."
                )
                QMessageBox.information(self, "Успіх Gemini", f"З'єднання успішне!\nМодель: {model}\nВідповідь: {resp.text.strip()}")
            except Exception as e:
                QMessageBox.critical(self, "Помилка Gemini", f"Не вдалося підключитися до Gemini:\n{e}")

        elif prov in ("groq", "grok"):
            key = self.grok_key_input.text().strip()
            model = self.grok_model_combo.currentText().strip()
            if not key:
                QMessageBox.warning(self, "API Key Missing", "Введіть Groq API Key (gsk_...) для перевірки.")
                return
            try:
                from openai import OpenAI
                client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "Скажи одне слово: Працює"}],
                    max_tokens=20
                )
                ans = resp.choices[0].message.content or ""
                QMessageBox.information(self, "Успіх Groq", f"З'єднання з Groq успішне!\nМодель: {model}\nВідповідь: {ans.strip()}")
            except Exception as e:
                QMessageBox.critical(self, "Помилка Groq", f"Не вдалося підключитися до Groq API (https://api.groq.com/openai/v1):\n{e}")

    def _save_and_apply(self):
        prov = self.provider_combo.currentData() or "groq"
        g_key = self.gemini_key_input.text().strip()
        g_model = self.gemini_model_combo.currentText().strip()
        gr_key = self.grok_key_input.text().strip()
        gr_model = self.grok_model_combo.currentText().strip()

        audio_mode = self.audio_mode_combo.currentData() or "speaker"
        spk_dev = self.speaker_combo.currentData() or ""
        mic_dev = self.mic_combo.currentData() or ""

        silence_dur = self.silence_slider.value() / 10.0
        min_speech_dur = self.min_speech_slider.value() / 10.0
        energy_thresh = self.energy_slider.value() / 1000.0
        stealth_mode = bool(self.stealth_combo.currentData())

        AppConfig.set_ai_provider(prov)
        AppConfig.set_gemini_api_key(g_key)
        AppConfig.set_gemini_model(g_model)
        AppConfig.set_groq_api_key(gr_key)
        AppConfig.set_groq_model(gr_model)
        AppConfig.set_audio_mode(audio_mode)
        AppConfig.set_speaker_device(spk_dev)
        AppConfig.set_mic_device(mic_dev)
        AppConfig.set_silence_duration(silence_dur)
        AppConfig.set_min_speech_duration(min_speech_dur)
        AppConfig.set_energy_threshold(energy_thresh)
        AppConfig.set_stealth_mode(stealth_mode)

        self.settings_saved.emit()
        self.accept()


# ---------------------------------------------------------------------------
# Main Window: Frameless Invisible Overlay (v1 HUD Layout)
# ---------------------------------------------------------------------------
class GhostOverlayWindow(QWidget):
    """
    Main transparent overlay window (v1 HUD).
    - SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE) ensures 100% invisibility
      during screen sharing across Zoom, Google Meet, MS Teams, Discord, and OBS.
    - Draggable anywhere, stay-on-top, tool window.
    - Audio dropdown matches exact layout:
      1. Speaker Only (Interviewer)
      2. Microphone Only (Me)
      3. Both Speaker and Microphone
    """
    def __init__(self):
        super().__init__()
        self._drag_pos = None

        self.setWindowTitle("Ghost Pilot Overlay")
        self.setMinimumSize(440, 360)
        self.resize(520, 620)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._build_ui()
        self._position_on_screen()
        self._init_workers()

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_stealth_mode()

    def _apply_stealth_mode(self):
        stealth = AppConfig.get_stealth_mode()
        hwnd = int(self.winId())
        apply_capture_exclusion(hwnd, stealth)
        if hasattr(self, "footer_label"):
            if stealth:
                self.footer_label.setText("🛡️ Screen-Share Invisibility: ACTIVE (Невидимий)")
                self.footer_label.setStyleSheet("color: #10b981; font-weight: bold;")
            else:
                self.footer_label.setText("📷 Screen Capture Allowed: VISIBLE (Можна скрінити)")
                self.footer_label.setStyleSheet("color: #f59e0b; font-weight: bold;")

    def _toggle_stealth_mode(self):
        new_state = not AppConfig.get_stealth_mode()
        AppConfig.set_stealth_mode(new_state)
        self._apply_stealth_mode()

    def _position_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            x = geom.width() - self.width() - 40
            y = 60
            self.move(x, y)

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)

        # Outer acrylic glass container
        self.container = QFrame()
        self.container.setObjectName("MainContainer")
        self.container.setStyleSheet("""
            QFrame#MainContainer {
                background-color: rgba(13, 17, 26, 0.94);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 14px;
            }
        """)
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(14, 12, 14, 12)
        container_layout.setSpacing(10)

        # -------------------------------------------------------------
        # Header Bar (v1 Clean Layout)
        # -------------------------------------------------------------
        header = QHBoxLayout()
        header.setSpacing(8)

        # Title / Brand
        title_box = QHBoxLayout()
        title_box.setSpacing(6)
        logo_icon = QLabel("👻")
        logo_icon.setFont(QFont("Segoe UI Emoji", 12))
        title_box.addWidget(logo_icon)

        app_title = QLabel("GHOST PILOT")
        app_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        app_title.setStyleSheet("color: #f8fafc; letter-spacing: 0.8px;")
        title_box.addWidget(app_title)
        header.addLayout(title_box)

        # Status Pill
        self.status_pill = StatusPill()
        header.addWidget(self.status_pill)

        # Mini Audio Visualizer
        self.visualizer = MiniAudioVisualizer()
        header.addWidget(self.visualizer)

        header.addStretch()

        # Audio Mode Selector Dropdown (Exact match to user's design)
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("AudioModeCombo")
        self.mode_combo.setStyleSheet("""
            QComboBox#AudioModeCombo {
                background-color: #1e222b;
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 7px;
                padding: 4px 8px;
                padding-right: 22px;
                color: #f1f5f9;
                font-family: 'Segoe UI';
                font-weight: 600;
                font-size: 11px;
            }
            QComboBox#AudioModeCombo:hover {
                border: 1px solid #38bdf8;
                background-color: #252b36;
            }
            QComboBox#AudioModeCombo::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 18px;
                border-left: none;
            }
            QComboBox#AudioModeCombo::down-arrow {
                width: 0;
                height: 0;
                border-left: 3px solid transparent;
                border-right: 3px solid transparent;
                border-top: 4px solid #94a3b8;
            }
            QComboBox#AudioModeCombo QAbstractItemView {
                background-color: #22252a;
                color: #e2e8f0;
                selection-background-color: #0078d4;
                selection-color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 7px;
                padding: 4px;
                outline: none;
                font-family: 'Segoe UI';
                font-size: 11px;
                font-weight: 600;
            }
        """)
        self.mode_combo.addItem("Speaker Only (Interviewer)", "speaker")
        self.mode_combo.addItem("Microphone Only (Me)", "mic")
        self.mode_combo.addItem("Both Speaker and Microphone", "both")

        cur_mode = AppConfig.get_audio_mode()
        idx = self.mode_combo.findData(cur_mode)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_combo_changed)
        style_combobox(self.mode_combo)
        header.addWidget(self.mode_combo)

        # Control Buttons
        self.pause_btn = QPushButton("⏸")
        self.pause_btn.setToolTip("Pause/Resume Listening")
        self.pause_btn.setFixedSize(28, 28)
        self.pause_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.pause_btn.setStyleSheet(self._control_btn_style())
        self.pause_btn.clicked.connect(self._toggle_pause)
        header.addWidget(self.pause_btn)

        self.clear_btn = QPushButton("🗑")
        self.clear_btn.setToolTip("Clear Conversation Feed")
        self.clear_btn.setFixedSize(28, 28)
        self.clear_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.clear_btn.setStyleSheet(self._control_btn_style())
        self.clear_btn.clicked.connect(self._clear_chat)
        header.addWidget(self.clear_btn)

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setToolTip("Settings & Keys")
        self.settings_btn.setFixedSize(28, 28)
        self.settings_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.settings_btn.setStyleSheet(self._control_btn_style())
        self.settings_btn.clicked.connect(self._open_settings)
        header.addWidget(self.settings_btn)

        self.min_btn = QPushButton("—")
        self.min_btn.setToolTip("Minimize")
        self.min_btn.setFixedSize(28, 28)
        self.min_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.min_btn.setStyleSheet(self._control_btn_style())
        self.min_btn.clicked.connect(self.showMinimized)
        header.addWidget(self.min_btn)

        self.close_btn = QPushButton("✕")
        self.close_btn.setToolTip("Close Application")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.close_btn.setStyleSheet(self._control_btn_style(hover_color="#f43f5e"))
        self.close_btn.clicked.connect(self.close)
        header.addWidget(self.close_btn)

        container_layout.addLayout(header)

        # -------------------------------------------------------------
        # Chat Feed Scroll Area (v1 Clean Layout)
        # -------------------------------------------------------------
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: rgba(255, 255, 255, 0.04);
                width: 6px;
                margin: 0;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.2);
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(56, 189, 248, 0.5);
            }
        """)

        self.chat_container = QWidget()
        self.chat_container.setStyleSheet("background: transparent;")
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setContentsMargins(2, 4, 4, 4)
        self.chat_layout.setSpacing(10)
        self.chat_layout.addStretch()

        self.scroll_area.setWidget(self.chat_container)
        container_layout.addWidget(self.scroll_area)

        # Empty state welcome card
        self._add_welcome_card()

        # -------------------------------------------------------------
        # Bottom Status Bar & Resize Handle
        # -------------------------------------------------------------
        footer = QHBoxLayout()
        footer.setContentsMargins(4, 0, 0, 0)

        self.footer_label = QLabel()
        self.footer_label.setFont(QFont("Segoe UI", 8))
        self.footer_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.footer_label.setToolTip("Клікніть, щоб увімкнути/вимкнути невидимість вікна для скріншотів")
        self.footer_label.mousePressEvent = lambda e: self._toggle_stealth_mode()
        footer.addWidget(self.footer_label)
        self._apply_stealth_mode()

        footer.addStretch()

        self.size_grip = QSizeGrip(self)
        self.size_grip.setStyleSheet("width: 14px; height: 14px;")
        footer.addWidget(self.size_grip)

        container_layout.addLayout(footer)
        root_layout.addWidget(self.container)

    def _control_btn_style(self, hover_color: str = "#38bdf8") -> str:
        return f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.05);
                color: #94a3b8;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                font-family: 'Segoe UI';
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.12);
                color: {hover_color};
                border: 1px solid {hover_color};
            }}
        """

    def _on_mode_combo_changed(self):
        new_mode = self.mode_combo.currentData()
        if hasattr(self, "audio_worker"):
            self.audio_worker.set_audio_mode(new_mode)

    def _add_welcome_card(self):
        self.welcome_frame = QFrame()
        self.welcome_frame.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.03);
                border: 1px dashed rgba(255, 255, 255, 0.12);
                border-radius: 10px;
                padding: 12px;
            }
        """)
        w_layout = QVBoxLayout(self.welcome_frame)
        w_layout.setSpacing(6)

        title = QLabel("Ghost Pilot — Автономний AI Копілот")
        title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        title.setStyleSheet("color: #38bdf8;")
        w_layout.addWidget(title)

        desc = QLabel(
            "• 🎧 3 режими аудіо: Speaker Only (Interviewer), Microphone Only (Me), Both.\n"
            "• 🤖 Підтримка двох AI провайдерів: Google Gemini та Groq (LPU).\n"
            "• 🛡️ Режим невидимки: вікно 100% приховано від демонстрації екрана (WDA_EXCLUDEFROMCAPTURE).\n"
            "• 🌐 Автоматично визначає та відповідає мовою запитання (укр, англ тощо)."
        )
        desc.setFont(QFont("Segoe UI", 8))
        desc.setStyleSheet("color: #94a3b8; line-height: 1.4;")
        w_layout.addWidget(desc)

        self.chat_layout.insertWidget(0, self.welcome_frame)

    # -----------------------------------------------------------------
    # Background Worker Orchestration
    # -----------------------------------------------------------------
    def _init_workers(self):
        # 1. AI Worker
        self.ai_worker = AIWorker()
        self.ai_worker.answer_received.connect(self._on_answer_received)
        self.ai_worker.status_changed.connect(self._on_status_changed)
        self.ai_worker.error_occurred.connect(self._on_error_occurred)
        self.ai_worker.start()

        # 2. Audio Capture Worker
        self.audio_worker = AudioCaptureWorker()
        self.audio_worker.audio_level.connect(self.visualizer.set_level)
        self.audio_worker.audio_segment_ready.connect(self._on_audio_segment_ready)
        self.audio_worker.status_changed.connect(self._on_status_changed)
        self.audio_worker.error_occurred.connect(self._on_error_occurred)
        self.audio_worker.start()

    @pyqtSlot(bytes, float)
    def _on_audio_segment_ready(self, wav_bytes: bytes, duration: float):
        self.ai_worker.enqueue_audio(wav_bytes, duration)

    @pyqtSlot(str, str, float, str)
    def _on_answer_received(self, question: str, answer: str, latency: float, provider_label: str):
        if hasattr(self, "welcome_frame") and self.welcome_frame:
            self.welcome_frame.hide()

        card = MessageCard(question, answer, latency, provider_label)
        idx = max(0, self.chat_layout.count() - 1)
        self.chat_layout.insertWidget(idx, card)

        QTimer.singleShot(50, self._scroll_to_bottom)

    @pyqtSlot(str, str)
    def _on_status_changed(self, text: str, badge_type: str):
        self.status_pill.set_status(text, badge_type)

    @pyqtSlot(str)
    def _on_error_occurred(self, err_msg: str):
        self.status_pill.set_status(err_msg, "error")

    def _scroll_to_bottom(self):
        vbar = self.scroll_area.verticalScrollBar()
        vbar.setValue(vbar.maximum())

    # -----------------------------------------------------------------
    # UI Control Actions
    # -----------------------------------------------------------------
    def _toggle_pause(self):
        is_paused = getattr(self.audio_worker, "_paused", False)
        new_state = not is_paused
        self.audio_worker.set_paused(new_state)
        if new_state:
            self.pause_btn.setText("▶")
            self.pause_btn.setToolTip("Resume Listening")
        else:
            self.pause_btn.setText("⏸")
            self.pause_btn.setToolTip("Pause Listening")

    def _clear_chat(self):
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._add_welcome_card()

    def _open_settings(self):
        dialog = SettingsDialog(self)
        dialog.settings_saved.connect(self._on_settings_applied)
        dialog.exec()

    def _on_settings_applied(self):
        # Update audio worker
        self.audio_worker.update_settings(
            audio_mode=AppConfig.get_audio_mode(),
            speaker_device=AppConfig.get_speaker_device(),
            mic_device=AppConfig.get_mic_device(),
            silence_dur=AppConfig.get_silence_duration(),
            min_speech_dur=AppConfig.get_min_speech_duration(),
            energy_thresh=AppConfig.get_energy_threshold()
        )
        # Update header audio mode dropdown
        idx = self.mode_combo.findData(AppConfig.get_audio_mode())
        if idx >= 0:
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentIndex(idx)
            self.mode_combo.blockSignals(False)

        # Update AI worker
        self.ai_worker.update_credentials(
            provider=AppConfig.get_ai_provider(),
            gemini_key=AppConfig.get_gemini_api_key(),
            gemini_model=AppConfig.get_gemini_model(),
            groq_key=AppConfig.get_groq_api_key(),
            groq_model=AppConfig.get_groq_model()
        )
        # Update Stealth Mode (Window Invisibility)
        self._apply_stealth_mode()

        self.status_pill.set_status("Налаштування збережено", "listening")

    # -----------------------------------------------------------------
    # Frameless Window Dragging Anywhere
    # -----------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def closeEvent(self, event):
        logger.info("Closing Ghost Pilot...")
        if hasattr(self, "audio_worker"):
            self.audio_worker.stop()
        if hasattr(self, "ai_worker"):
            self.ai_worker.stop()
        event.accept()


# ---------------------------------------------------------------------------
# Main Application Bootstrap
# ---------------------------------------------------------------------------
def create_dark_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0d111a"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#f8fafc"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#1e222b"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#161b24"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#1e222b"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#f8fafc"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#f8fafc"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#1e222b"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#f8fafc"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#38bdf8"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#38bdf8"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#0078d4"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    return palette


def main():
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

    app = QApplication(sys.argv)
    app.setApplicationName("Ghost Pilot")
    app.setStyle("Fusion")
    app.setPalette(create_dark_palette())

    app.setStyleSheet("""
        QListView, QAbstractItemView, QMenu {
            background-color: #1e222b;
            color: #f8fafc;
            border: 1px solid rgba(255, 255, 255, 0.16);
            border-radius: 6px;
            padding: 4px;
            selection-background-color: #0078d4;
            selection-color: #ffffff;
            outline: none;
        }
        QListView::item, QAbstractItemView::item, QMenu::item {
            color: #f8fafc;
            background-color: transparent;
            padding: 6px 10px;
            border-radius: 4px;
            min-height: 22px;
        }
        QListView::item:hover, QAbstractItemView::item:hover, QMenu::item:selected {
            background-color: rgba(56, 189, 248, 0.2);
            color: #ffffff;
        }
        QListView::item:selected, QAbstractItemView::item:selected {
            background-color: #0078d4;
            color: #ffffff;
        }
    """)

    font = QFont("Segoe UI", 9)
    app.setFont(font)

    window = GhostOverlayWindow()
    window.show()

    logger.info("Ghost Pilot launched successfully.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
