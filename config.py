"""
Configuration module for DesktopAssistant.
Contains application constants, status definitions, color themes, and logging setup.
"""

import os
import logging
from enum import Enum
from pathlib import Path

# Application Metadata
APP_NAME = "DesktopAssistant"
APP_VERSION = "1.0.0"
SINGLE_INSTANCE_MUTEX = "DesktopAssistant_SingleInstance_Mutex_1052"

# System Tray Status States
class AssistantState(Enum):
    READY = "READY"
    LISTENING = "LISTENING"
    WAITING_FOR_TRANSCRIPT = "WAITING_FOR_TRANSCRIPT"
    PROCESSING = "PROCESSING"
    EXECUTING = "EXECUTING"
    ERROR = "ERROR"

# Tray Icon Color Scheme (RGB tuples)
STATE_COLORS = {
    AssistantState.READY: (16, 185, 129),                # Emerald Green
    AssistantState.LISTENING: (59, 130, 246),             # Vibrant Blue
    AssistantState.WAITING_FOR_TRANSCRIPT: (14, 165, 233),# Sky Cyan
    AssistantState.PROCESSING: (245, 158, 11),            # Amber Yellow
    AssistantState.EXECUTING: (168, 85, 247),             # Purple
    AssistantState.ERROR: (239, 68, 68),                  # Red
}

# Wispr Input Bridge & Trigger Settings
ACTIVATION_HOTKEY = "<ctrl>+<alt>+a"
WISPR_TRIGGER_SHORTCUT = "<win>+<shift>+space"  # Configured Wispr Flow Windows dictation shortcut

SPEECH_INACTIVITY_TIMEOUT_SECONDS = 2.0  # Finalize transcript after 2 seconds of inactivity
OVERALL_SAFETY_TIMEOUT_SECONDS = 30.0    # 30-second overall session timeout limit
RESTORE_FOCUS_DELAY_MS = 80
ERROR_RECOVERY_DELAY_SECONDS = 2.0

# Voice Output Settings
VOICE_RATE = 0  # Default SAPI speed (-10 to 10)
VOICE_VOLUME = 100  # Default SAPI volume (0 to 100)

# Logging Setup
BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "desktop_assistant.log"

def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configures application logger for local logging."""
    logger = logging.getLogger(APP_NAME)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    
    if not logger.handlers:
        # File handler
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s (%(threadName)s): %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter(
            "[%(levelname)s] %(message)s"
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
    return logger
