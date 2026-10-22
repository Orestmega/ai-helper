# Ghost Pilot 👻 - Hands-Free Autonomous Real-Time AI Copilot for Windows

Ghost Pilot is a 100% hands-free, autonomous real-time AI desktop assistant designed for Windows. It continuously monitors system audio (such as incoming speech from Zoom, Google Meet, Microsoft Teams, Discord, or YouTube), automatically detects questions using Voice Activity Detection (VAD), and generates instant, concise answers in an on-screen chat overlay that is **completely invisible to screen sharing and recording software**.

---

## 🌟 Key Features

1. **Invisible Screen-Share Overlay (Ghost Window)**:
   - Built with **PyQt6**.
   - Frameless, translucent dark glassmorphism, stays on top, tool window.
   - Utilizes the official Windows Win32 API:
     ```python
     ctypes.windll.user32.SetWindowDisplayAffinity(int(window.winId()), 0x00000011) # WDA_EXCLUDEFROMCAPTURE
     ```
   - **100% invisible** to Zoom, Google Meet, Microsoft Teams, Discord, and OBS Studio screen capture. You see it on your monitor, but anyone watching your screenshare sees straight through it.

2. **Exclusive Incoming Audio Loopback Capture (Zero Microphone Recording)**:
   - **Exclusively Incoming Sound**: Captures only the incoming audio (what you hear in your headphones or speakers). Your own physical microphone is **never** recorded or listened to.
   - **Two Flexible Capture Modes**:
     - **🌐 Увесь системний звук (All System Audio)**: Captures everything playing through your speakers/headphones (YouTube, Telegram voice messages, browser videos, media players, Discord, Zoom, etc.).
     - **📞 Тільки додатки для дзвінків (Call Apps Only)**: Selectively filters speech so questions are only captured from active conference/call applications (Discord, Zoom, Google Meet, MS Teams, Skype, Slack, Webex, etc.). Other background sounds (e.g. YouTube music, browser noise) are automatically ignored.
   - Real-time continuous Voice Activity Detection (VAD):
     - Adaptive noise-floor calibration tuned to pick up quieter questions (RMS ~0.008).
     - Automatically detects when a sentence/question concludes followed by silence (~1.1s).
     - Encodes the speech into standard 16kHz mono 16-bit PCM WAV in memory.
     - Immediately resumes listening to subsequent speech.

3. **Strict Multilingual Question & Answer Matching**:
   - Analyzes speech in **ANY** spoken language (Ukrainian, English, Polish, German, French, etc.).
   - **Strict Language Guarantee**: If the question is in Ukrainian, both the question transcription and the answer are generated strictly in Ukrainian. Never defaults to English when a foreign/different language is spoken.

4. **Universal & Dynamic Gemini Multimodal API**:
   - Official `google-genai` SDK (`from google import genai`).
   - Dynamically configurable model identifier (e.g., `gemini-2.5-flash`, `gemini-2.0-flash`, `gemini-3.8-flash`, `gemini-3.5-flash-lite`, or any custom model name).
   - Prompt discards background chatter and greetings with `NO_QUESTION`.

5. **Multi-Threaded & Stutter-Free Performance**:
   - Audio capture and AI requests execute on separate background `QThread` workers.
   - Smooth 60 FPS UI with real-time dynamic audio visualizer / VU meter.
   - Status indicator badges (`LISTENING`, `SPEECH DETECTED`, `AI THINKING`, `ANSWERED`, `PAUSED`, `ATTENTION`).
   - One-click copy answer to clipboard.

---

## 📁 Project Structure

```
c:/ai helper/
├── main.py              # Main application entry point (UI, Audio Worker, Gemini Worker)
├── requirements.txt     # Python dependencies
├── run.bat              # One-click Windows setup and launch script
├── .env.example         # Template for environment configuration
├── .env                 # Active configuration (API keys, models, VAD settings)
└── README.md            # Comprehensive documentation & testing guide
```

---

## 🚀 Quick Start (One-Click)

### Method 1: Using `run.bat` (Recommended)

Simply double-click `run.bat` or run it from the command line:

```cmd
run.bat
```

The script will automatically:
1. Verify Python 3.10+ installation.
2. Create an isolated virtual environment (`.venv`).
3. Initialize `.env` from `.env.example` if not present.
4. Install and upgrade all dependencies from `requirements.txt`.
5. Launch the Ghost Pilot desktop overlay with capture invisibility active.

### Method 2: Manual Installation

```cmd
:: 1. Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\activate

:: 2. Install dependencies
pip install -r requirements.txt

:: 3. Configure your API key
copy .env.example .env
:: (Edit .env and add your GEMINI_API_KEY)

:: 4. Run the application
python main.py
```

---

## ⚙️ Configuration

You can configure settings either by editing `.env` or directly through the **in-app Settings modal** (click the **⚙** gear button on the overlay header):

| Setting | Environment Variable | Default | Description |
| :--- | :--- | :--- | :--- |
| **AI Provider** | `AI_PROVIDER` | `groq` | Active engine: `groq` (Ultra-fast LPU inference) or `gemini` (Google AI Studio). |
| **Groq API Key** | `GROQ_API_KEY` | *(empty)* | Key from [console.groq.com](https://console.groq.com/) (starts with `gsk_`). |
| **Groq Model** | `GROQ_MODEL` | `qwen/qwen3.8-27b` | Groq model: `qwen/qwen3.8-27b`, `openai/gpt-oss-120b`, `llama-3.3-70b-versatile`, etc. |
| **Gemini API Key** | `GEMINI_API_KEY` | *(empty)* | Key from [Google AI Studio](https://aistudio.google.com/). |
| **Gemini Model** | `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model: `gemini-2.5-flash`, `gemini-2.0-flash`, `gemini-3.8-flash`, etc. |
| **Audio Mode** | `AUDIO_MODE` | `speaker` | Audio source: `speaker` (Loopback only), `mic` (Microphone only), `both` (Mixed). |
| **Silence Duration** | `VAD_SILENCE_SECONDS` | `1.1` | Silence required (in seconds) to mark end-of-question (0.8s – 2.5s). |
| **Min Speech Duration** | `VAD_MIN_SPEECH_SECONDS` | `0.6` | Minimum speech duration to filter out clicks/coughs (0.4s – 2.5s). |
| **Energy Threshold** | `VAD_ENERGY_THRESHOLD` | `0.015` | RMS energy threshold for speech trigger. |
| **Stealth Mode** | `STEALTH_MODE` | `true` | `true` = hidden from screenshots/calls; `false` = visible for screenshots. |

---

## 🧪 Testing Screen-Capture Invisibility

To verify that the window is completely invisible to screen recording and conferencing software:

### Test 1: Windows Snipping Tool (Quickest)
1. Launch Ghost Pilot (ensure the window is visible on your screen).
2. Press `Win + Shift + S` or open the Windows **Snipping Tool**.
3. Select "Full Screen Snip" or drag a selection over Ghost Pilot.
4. Observe the captured screenshot: the Ghost Pilot window is **completely excluded** (or appears as a transparent/black pass-through area where desktop wallpaper/background apps show).

### Test 2: OBS Studio (Live Stream / Recording)
1. Open **OBS Studio**.
2. Add a new source: **Display Capture** (capturing your primary monitor).
3. Look at the OBS preview canvas: Ghost Pilot is visible on your physical screen, but **100% missing from the OBS preview and recordings**.

### Test 3: Zoom / Discord / MS Teams / Google Meet
1. Start a meeting or voice call.
2. Select **Share Screen** -> **Entire Screen** (Desktop 1).
3. Check the screen-share preview or ask a friend: they will see your browser, code editor, and desktop, but **never the Ghost Pilot window**.

---

## 💡 How It Works Under the Hood

```
   ┌─────────────────────────────────────────────────────────┐
   │             System Audio (Zoom / Meet / Discord)         │
   └───────────────────────────┬─────────────────────────────┘
                               │ WASAPI Loopback Capture (Zero Mic)
                               ▼
   ┌─────────────────────────────────────────────────────────┐
   │ AudioLoopbackWorker (QThread)                           │
   │  - 16 kHz Mono Streaming (Output Loopback)              │
   │  - Mode: 'all_system' or 'calls_only' (pycaw + windows) │
   │  - Energy-based Voice Activity Detection (VAD)          │
   │  - Slices audio when ~1.1s of silence occurs            │
   └───────────────────────────┬─────────────────────────────┘
                               │ 16kHz WAV In-Memory Bytes
                               ▼
   ┌─────────────────────────────────────────────────────────┐
   │ GeminiWorker (QThread)                                  │
   │  - google-genai Multimodal API                          │
   │  - Evaluates for question vs. background talk           │
   │  - Returns strictly: Q: [Question] / A: [Direct Answer] │
   └───────────────────────────┬─────────────────────────────┘
                               │ Q&A Result Signal
                               ▼
   ┌─────────────────────────────────────────────────────────┐
   │ GhostOverlayWindow (PyQt6 UI)                           │
   │  - WDA_EXCLUDEFROMCAPTURE (SetWindowDisplayAffinity)    │
   │  - Renders question & answer card bubble                │
   │  - Auto-scroll & 1-click clipboard copy                 │
   └─────────────────────────────────────────────────────────┘
```

---

## 📋 Keyboard & Mouse Controls

- **Move Window**: Click and drag anywhere on the window.
- **Resize Window**: Click and drag the bottom-right corner grip.
- **Capture Mode Selector (`🌐 Увесь системний звук` / `📞 Тільки дзвінки`)**: Click to instantly toggle between capturing all PC sounds or selectively capturing call applications only, as well as choosing specific playback headphones/speakers.
- **Pause/Resume**: Click `⏸` / `▶` to pause or resume audio listening.
- **Clear Feed**: Click `🗑` to clear the conversation history.
- **Settings**: Click `⚙` to open API key, model, audio mode, and sensitivity sliders.
- **Copy Answer**: Click `📋 Copy Answer` on any answer card.
