"""
Local Text-to-Speech (TTS) module using Windows SAPI via pywin32.
Runs speech synthesis in a background worker thread to ensure non-blocking UI.
"""

import threading
import queue
import logging
from typing import Callable, Optional
from config import VOICE_RATE, VOICE_VOLUME

logger = logging.getLogger("DesktopAssistant.VoiceOutput")

try:
    import win32com.client
    import pythoncom
    SAPI_AVAILABLE = True
except ImportError:
    SAPI_AVAILABLE = False
    logger.warning("pywin32 not found. SAPI voice output will run in fallback simulation mode.")


class VoiceOutput:
    """
    Manages local Text-to-Speech output via Windows SAPI.
    Uses a thread-safe queue to process speech requests asynchronously.
    """

    def __init__(
        self,
        rate: int = VOICE_RATE,
        volume: int = VOICE_VOLUME,
        state_callback: Optional[Callable[[str], None]] = None
    ):
        self.rate = rate
        self.volume = volume
        self.state_callback = state_callback
        
        self._speech_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self):
        """Start the background speech processing thread."""
        with self._lock:
            if self._worker_thread is not None and self._worker_thread.is_alive():
                return
            self._stop_event.clear()
            self._worker_thread = threading.Thread(
                target=self._speech_worker,
                name="VoiceOutputWorker",
                daemon=True
            )
            self._worker_thread.start()
            logger.info("VoiceOutput background worker started.")

    def stop(self):
        """Stop the background speech worker cleanly."""
        self._stop_event.set()
        self._speech_queue.put(None)  # Sentinel to unblock queue.get()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
        logger.info("VoiceOutput background worker stopped.")

    def speak(self, text: str, on_done: Optional[Callable[[], None]] = None):
        """
        Queue text to be spoken asynchronously.
        
        Args:
            text: The sentence/phrase to speak.
            on_done: Optional callback invoked after speech completes.
        """
        if not text or not text.strip():
            if on_done:
                on_done()
            return
            
        logger.info(f"Queuing TTS text: '{text}'")
        self._speech_queue.put((text.strip(), on_done))

    def _speech_worker(self):
        """Worker loop that initializes COM, reads from queue, and speaks text."""
        speaker = None
        if SAPI_AVAILABLE:
            try:
                pythoncom.CoInitialize()
                speaker = win32com.client.Dispatch("SAPI.SpVoice")
                speaker.Rate = self.rate
                speaker.Volume = self.volume
            except Exception as e:
                logger.error(f"Failed to initialize SAPI SpVoice: {e}")
                speaker = None

        while not self._stop_event.is_set():
            try:
                item = self._speech_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is None:
                # Stop sentinel received
                break

            text, on_done = item

            # Notify state change to SPEAKING
            if self.state_callback:
                try:
                    self.state_callback("SPEAKING")
                except Exception as cb_err:
                    logger.error(f"State callback error before speaking: {cb_err}")

            try:
                if speaker:
                    logger.debug(f"Speaking via SAPI: '{text}'")
                    # SAPI Speak flag 0 = Synchronous speak within worker thread
                    speaker.Speak(text)
                else:
                    logger.info(f"[TTS Fallback Log]: {text}")
            except Exception as e:
                logger.error(f"Error during speech synthesis: {e}")
            finally:
                self._speech_queue.task_done()
                
                # Notify state change back to READY
                if self.state_callback:
                    try:
                        self.state_callback("READY")
                    except Exception as cb_err:
                        logger.error(f"State callback error after speaking: {cb_err}")
                        
                if on_done:
                    try:
                        on_done()
                    except Exception as cb_err:
                        logger.error(f"TTS on_done callback error: {cb_err}")

        if SAPI_AVAILABLE:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
