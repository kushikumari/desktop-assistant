# DesktopAssistant 🎙️💻

A complete, lightweight, production-ready Windows desktop voice assistant integrated with **Wispr Flow**.

---

## 🌟 Overview & Architecture

`DesktopAssistant` runs as a native background application in the Windows System Tray. It processes transcribed spoken commands from **Wispr Flow** (or local test inputs), executes safe Windows actions, calculates math expressions, answers local knowledge questions, and speaks responses back locally using Windows SAPI Text-to-Speech.

### 🔄 Target User Experience Workflow

```
1. DesktopAssistant runs silently in the Windows System Tray (Status: READY).
2. User works normally in any application (e.g. Chrome, VS Code, Word).
3. User presses single shortcut: Ctrl + Alt + A.
4. DesktopAssistant wakes up (Status: LISTENING).
5. DesktopAssistant focuses native text entry control & confirms focus (FOCUS_CONFIRMED).
6. DesktopAssistant automatically triggers Wispr Flow dictation.
7. System state transitions to WAITING_FOR_TRANSCRIPT.
8. User speaks naturally ("Open Chrome", "What is 20 percent of 500?").
9. Wispr Flow transcribes text directly into the focused native entry control.
10. DesktopAssistant detects text changes (TEXT_CHANGED) and starts a 2.0-second inactivity timer.
11. Additional transcript updates reset the 2.0-second inactivity timer.
12. After 2.0 continuous seconds of silence/inactivity, speech end is confirmed (SPEECH_END_CONFIRMED).
13. Finalized transcript is passed to command_processor.py (State: PROCESSING → EXECUTING).
14. Target action executes (Chrome opens) & local Windows SAPI speaks response ("Opening Chrome.").
15. Focus is restored to the user's previous application.
16. DesktopAssistant returns to READY status.
```

---

## 📊 State Machine & Timers

`DesktopAssistant` implements an explicit deterministic state machine with automatic recovery watchdogs to guarantee the assistant never becomes stuck:

```
READY
  └──> LISTENING
         └──> WAITING_FOR_TRANSCRIPT
                └──> PROCESSING
                       └──> EXECUTING
                              └──> READY

ERROR
  └──> Auto-Recovery Timer (2.0s) ──> READY
```

- **Speech Inactivity Finalization Timer:** 2.0 continuous seconds of speech/input inactivity finalizes the transcript and executes the command.
- **Overall Session Safety Timeout:** 30.0-second overall timeout prevents the assistant from remaining active if no speech is uttered.
- **Single Instance Enforcement:** Uses Windows Mutex (`DesktopAssistant_SingleInstance_Mutex_1052`) to prevent duplicate background instances.
- **Wispr Trigger Shortcut:** Automatically simulates configured Wispr shortcut (`WISPR_TRIGGER_SHORTCUT`, default `<win>+<shift>+space` in `config.py`).

---

## 🏗️ Project Structure

```
DesktopAssistant/
├── DesktopAssistant.exe   # Pre-built standalone single-file Windows executable
├── main.py                # App entry point, single-instance mutex, system tray, hotkeys, state machine
├── command_processor.py   # Intent recognition & response generation pipeline
├── windows_actions.py     # Safe Windows app launch handlers (Chrome, WhatsApp, Explorer, etc.)
├── calculator.py          # Safe AST-based math evaluator (No eval())
├── knowledge.py           # Local technical knowledge base (RAM, CPU, AI, etc.)
├── voice_output.py        # Local Text-to-Speech (TTS) via Windows SAPI
├── input_bridge.py        # Native Wispr Flow text capture, focus confirmation & 2s inactivity timer
├── startup_manager.py     # Per-user Windows Registry startup toggle manager
├── config.py             # Color tokens, state definitions & logging setup
├── requirements.txt       # Python package dependencies
├── README.md              # Documentation & usage manual
└── tests/                 # Automated pytest unit test suite (43 test cases)
    ├── test_calculator.py
    ├── test_knowledge.py
    ├── test_windows_actions.py
    ├── test_command_processor.py
    ├── test_input_bridge.py
    ├── test_startup_manager.py
    └── test_state_machine.py
```

---

## 🚀 Running DesktopAssistant

### Option 1: Standalone Executable (Recommended)
Simply double-click **`DesktopAssistant.exe`** in the project folder or `dist/` directory.

- No Python environment required.
- Runs windowless in the background with a System Tray icon.

### Option 2: Running from Source
Requires Python 3.11+ on Windows:

```powershell
pip install -r requirements.txt
python main.py
```

---

## ⚙️ Wispr Flow Setup & Configuration

1. **Wispr Flow Shortcut:** `DesktopAssistant` coordinates with Wispr Flow using the configured dictation shortcut defined in `config.py`:
   ```python
   WISPR_TRIGGER_SHORTCUT = "<win>+<shift>+space"
   ```
   *(If your Wispr Flow settings use a custom shortcut, set `WISPR_TRIGGER_SHORTCUT` in `config.py` accordingly).*

2. **Workflow:**
   - Press **`Ctrl + Alt + A`**.
   - Speak naturally.
   - Stop speaking.
   - Wait 2 seconds → Command executes!

---

## ⚙️ Windows Startup Integration

`DesktopAssistant` includes native per-user Windows startup support via the Registry (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`).

To enable or disable automatic startup:
1. Right-click the **DesktopAssistant** System Tray Icon.
2. Click **`Launch on Windows Startup`** to toggle startup status on/off.
3. A checkmark `[x]` will display when startup is enabled.

---

## 🗣️ Supported Commands & Verification

| Voice Command | Intent Category | System Action / Response |
| :--- | :--- | :--- |
| `"Open Chrome"` | `WINDOWS_ACTION` | Launches Chrome browser → *"Opening Chrome."* |
| `"Open WhatsApp"` | `WINDOWS_ACTION` | Opens WhatsApp app/protocol → *"Opening WhatsApp."* |
| `"Open files"` / `"Open File Explorer"` | `WINDOWS_ACTION` | Opens Windows Explorer → *"Opening File Explorer."* |
| `"Open calculator"` | `WINDOWS_ACTION` | Opens Windows Calculator → *"Opening Calculator."* |
| `"Open settings"` | `WINDOWS_ACTION` | Opens Windows Settings → *"Opening Settings."* |
| `"What time is it?"` | `TIME_DATE` | Speaks current local Windows time → *"The current time is 4:30 PM."* |
| `"What is 25 times 16?"` | `CALCULATOR` | Evaluates arithmetic expression → *"25 times 16 equals 400."* |
| `"What is 20 percent of 500?"` | `CALCULATOR` | Evaluates percentage math → *"20 percent of 500 equals 100."* |
| `"What is RAM?"` | `KNOWLEDGE` | Concise local response → *"RAM, or Random Access Memory..."* |
| `"exit"` / `"quit"` / `"stop"` | `EXIT` | Cleanly shuts down DesktopAssistant → *"Goodbye! Closing DesktopAssistant."* |

---

## 🧪 Testing & Local Injection Mode

### Running Automated Unit Tests
To run the complete automated unit test suite (43 test cases):

```powershell
pytest -v
```

### Local Interactive Command Testing (Without Wispr)
You can test the entire command pipeline without speaking:

1. Right-click the **DesktopAssistant** System Tray Icon.
2. Click **"Inject Command (Test Mode)..."**.
3. Type any command (e.g. `20 percent of 500` or `Open settings`) and press Enter.
4. The assistant will process the command and speak the output.

---

## 📦 Building PyInstaller Executable

To re-package `DesktopAssistant.exe` from source:

```powershell
pip install pyinstaller
pyinstaller --noconsole --onefile --name DesktopAssistant --hidden-import win32com.client --hidden-import pythoncom --hidden-import win32gui --hidden-import win32process --hidden-import win32api --hidden-import win32clipboard --hidden-import pystray --hidden-import pynput.keyboard --hidden-import PIL.Image --hidden-import PIL.ImageDraw main.py
```

The compiled standalone executable will be generated at `dist/DesktopAssistant.exe`.
