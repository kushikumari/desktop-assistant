"""
Wispr Flow Input Bridge for DesktopAssistant.
Coordinates:
1. Focus recording and genuine focused native Win32 text entry control.
2. Automatic Wispr Flow dictation trigger key simulation.
3. 2.0-second speech inactivity finalization timer.
4. 30.0-second overall session safety timeout.
5. Focus confirmation logging, modifier key release safety, Unicode text preservation.
"""

import time
import threading
import logging
import tkinter as tk
from typing import Callable, Optional

from config import (
    SPEECH_INACTIVITY_TIMEOUT_SECONDS,
    OVERALL_SAFETY_TIMEOUT_SECONDS,
    RESTORE_FOCUS_DELAY_MS,
    WISPR_TRIGGER_SHORTCUT
)

logger = logging.getLogger("DesktopAssistant.InputBridge")

# Win32 Constants & APIs
WM_CLIPBOARDUPDATE = 0x031D

try:
    import ctypes
    from ctypes import wintypes
    import win32gui
    import win32process
    import win32api
    import win32con
    import win32clipboard
    from pynput.keyboard import Controller, Key

    user32 = ctypes.windll.user32
    AddClipboardFormatListener = user32.AddClipboardFormatListener
    RemoveClipboardFormatListener = user32.RemoveClipboardFormatListener
    AddClipboardFormatListener.argtypes = [wintypes.HWND]
    AddClipboardFormatListener.restype = wintypes.BOOL
    RemoveClipboardFormatListener.argtypes = [wintypes.HWND]
    RemoveClipboardFormatListener.restype = wintypes.BOOL
    PYWIN32_AVAILABLE = True
except Exception as e:
    PYWIN32_AVAILABLE = False
    logger.warning(f"Win32 API setup warning: {e}")

keyboard_controller = Controller() if PYWIN32_AVAILABLE else None


def release_all_modifiers():
    """Releases all modifier keys (Ctrl, Alt, Shift, Win) to prevent stuck key states."""
    if not keyboard_controller:
        return
    modifier_keys = [
        Key.ctrl, Key.ctrl_l, Key.ctrl_r,
        Key.alt, Key.alt_l, Key.alt_r, Key.alt_gr,
        Key.shift, Key.shift_l, Key.shift_r,
        Key.cmd, Key.cmd_l, Key.cmd_r
    ]
    for key in modifier_keys:
        try:
            keyboard_controller.release(key)
        except Exception:
            pass


def send_wispr_shortcut():
    """
    Simulates pressing the configured Wispr Flow Windows shortcut (Win+Shift+Space).
    """
    if not keyboard_controller:
        logger.warning("[WISPR] Keyboard controller unavailable to trigger Wispr shortcut.")
        return

    logger.info(f"[WISPR] TRIGGER_REQUESTED: Triggering Wispr Flow shortcut '{WISPR_TRIGGER_SHORTCUT}'...")
    release_all_modifiers()
    time.sleep(0.05)

    try:
        # Press Win+Shift+Space
        keyboard_controller.press(Key.cmd)
        keyboard_controller.press(Key.shift)
        keyboard_controller.press(Key.space)
        time.sleep(0.06)
        keyboard_controller.release(Key.space)
        keyboard_controller.release(Key.shift)
        keyboard_controller.release(Key.cmd)
        release_all_modifiers()
        logger.info("[WISPR] LISTENING: Wispr Flow trigger keys sent.")
    except Exception as e:
        logger.error(f"[WISPR] TRIGGER_FAILED: Failed to send Wispr trigger keys: {e}")


class ContinuousClipboardListener(threading.Thread):
    """
    Background daemon thread that runs a Win32 message loop listening for
    WM_CLIPBOARDUPDATE (0x031D) events continuously as a secondary diagnostic channel.
    """

    def __init__(self, callback: Callable[[str, float], None]):
        super().__init__(daemon=True, name="WisprClipboardListener")
        self.callback = callback
        self.hwnd: Optional[int] = None
        self._stop_event = threading.Event()

    def run(self):
        if not PYWIN32_AVAILABLE:
            return

        try:
            wnd_class = win32gui.WNDCLASS()
            wnd_class.hInstance = win32gui.GetModuleHandle(None)
            wnd_class.lpszClassName = "WisprClipboardListenerClass"
            wnd_class.lpfnWndProc = self._wnd_proc
            try:
                class_atom = win32gui.RegisterClass(wnd_class)
            except Exception:
                pass

            self.hwnd = win32gui.CreateWindowEx(
                0, "WisprClipboardListenerClass", "WisprClipboardListenerWindow",
                0, 0, 0, 0, 0,
                win32con.HWND_MESSAGE, 0, wnd_class.hInstance, None
            )

            if AddClipboardFormatListener(self.hwnd):
                logger.info(f"[INPUT_BRIDGE] Continuous WM_CLIPBOARDUPDATE listener registered on HWND {self.hwnd}.")
            else:
                logger.error("[INPUT_BRIDGE] AddClipboardFormatListener failed.")

            win32gui.PumpMessages()
        except Exception as e:
            logger.error(f"[INPUT_BRIDGE] Error in clipboard listener thread: {e}")

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_CLIPBOARDUPDATE:
            now = time.time()
            text = self._read_clipboard_text()
            if text is not None:
                try:
                    self.callback(text, now)
                except Exception as cb_err:
                    logger.error(f"[INPUT_BRIDGE] Error in clipboard update callback: {cb_err}")
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _read_clipboard_text(self) -> Optional[str]:
        if not PYWIN32_AVAILABLE:
            return None
        try:
            win32clipboard.OpenClipboard()
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                win32clipboard.CloseClipboard()
                if data and isinstance(data, str):
                    return data.strip()
            win32clipboard.CloseClipboard()
        except Exception:
            pass
        return None

    def stop(self):
        self._stop_event.set()
        if self.hwnd and PYWIN32_AVAILABLE:
            try:
                RemoveClipboardFormatListener(self.hwnd)
                win32gui.PostMessage(self.hwnd, win32con.WM_QUIT, 0, 0)
            except Exception:
                pass


class WisprInputBridge:
    """
    Manages text input capture for Wispr Flow transcriptions.
    Provides focus confirmation, Wispr auto-triggering, 2-second speech inactivity finalization,
    and 30-second overall safety session timeout.
    """

    def __init__(
        self,
        command_callback: Callable[[str], None],
        state_callback: Optional[Callable[[str], None]] = None
    ):
        self.command_callback = command_callback
        self.state_callback = state_callback
        
        self.previous_hwnd: Optional[int] = None
        self._is_active = False
        self.wake_timestamp: float = 0.0
        self.initial_clipboard_text: Optional[str] = None
        
        self.last_transcript_text: str = ""
        self.last_finalized_text: str = ""
        self.last_finalized_time: float = 0.0

        # Background clipboard listener (secondary fallback/diagnostic channel)
        self.clipboard_listener: Optional[ContinuousClipboardListener] = None
        self._start_clipboard_listener()

        # Tkinter elements
        self.root: Optional[tk.Tk] = None
        self.entry: Optional[tk.Entry] = None
        
        # Timers
        self._overall_safety_timer: Optional[threading.Timer] = None
        self._inactivity_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def _start_clipboard_listener(self):
        """Starts background continuous clipboard listener thread."""
        try:
            self.clipboard_listener = ContinuousClipboardListener(callback=self.on_clipboard_updated)
            self.clipboard_listener.start()
        except Exception as e:
            logger.error(f"[INPUT_BRIDGE] Failed to start clipboard listener: {e}")

    def on_clipboard_updated(self, text: str, timestamp: float):
        """Callback invoked whenever WM_CLIPBOARDUPDATE fires."""
        if not self._is_active:
            return

        logger.info(f"[INPUT_BRIDGE] DIAGNOSTIC: WM_CLIPBOARDUPDATE detected at {timestamp:.3f}. Content: '{text}'")
        # If entry is empty, populate entry from clipboard update
        if self.entry and self.root and not self.entry.get().strip():
            if text and text != self.initial_clipboard_text:
                self.root.after(0, lambda: self._on_text_updated(text, source="CLIPBOARD_FALLBACK"))

    def record_foreground_window(self):
        """Records handle of the currently focused application window."""
        if PYWIN32_AVAILABLE:
            try:
                self.previous_hwnd = win32gui.GetForegroundWindow()
                title = win32gui.GetWindowText(self.previous_hwnd)
                logger.info(f"[INPUT_BRIDGE] Recorded previous active window: HWND {self.previous_hwnd} ('{title}')")
            except Exception as e:
                logger.warning(f"[INPUT_BRIDGE] Failed to record foreground window HWND: {e}")
                self.previous_hwnd = None
        else:
            self.previous_hwnd = None

    def restore_previous_window_focus(self):
        """Restores keyboard focus back to recorded previous window."""
        if not PYWIN32_AVAILABLE or not self.previous_hwnd:
            return

        try:
            hwnd = self.previous_hwnd
            if win32gui.IsWindow(hwnd):
                if win32gui.IsIconic(hwnd):
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                else:
                    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)

                current_thread = win32api.GetCurrentThreadId()
                target_thread, _ = win32process.GetWindowThreadProcessId(hwnd)
                
                if current_thread != target_thread:
                    win32process.AttachThreadInput(current_thread, target_thread, True)
                    win32gui.SetForegroundWindow(hwnd)
                    win32process.AttachThreadInput(current_thread, target_thread, False)
                else:
                    win32gui.SetForegroundWindow(hwnd)

                logger.info(f"[INPUT_BRIDGE] Restored window focus to HWND {hwnd}")
        except Exception as e:
            logger.warning(f"[INPUT_BRIDGE] Error restoring window focus: {e}")

    def create_ui(self, root: tk.Tk):
        """Initializes the Tkinter input window UI elements."""
        self.root = root
        
        self.root.title("DesktopAssistant Voice Input Bridge")
        self.root.geometry("460x85+400+300")
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#0F172A")
        
        lbl = tk.Label(
            self.root,
            text="Wispr Flow Voice Activation - Speak your command...",
            fg="#38BDF8",
            bg="#0F172A",
            font=("Segoe UI", 10, "bold")
        )
        lbl.pack(pady=(8, 4))

        self.entry = tk.Entry(
            self.root,
            font=("Segoe UI", 11),
            bg="#1E293B",
            fg="#F8FAFC",
            insertbackground="#38BDF8",
            relief="solid",
            bd=1
        )
        self.entry.pack(padx=16, pady=4, fill="x")

        self.entry.bind("<Return>", self._on_return_pressed)
        self.entry.bind("<Escape>", self._on_cancel)
        self.entry.bind("<Key>", self._on_key_typed)

        self.root.withdraw()

    def activate(self):
        """
        Wakes DesktopAssistant and starts voice input session:
        1. Logs wake event.
        2. Sets state to LISTENING.
        3. Clears input bridge.
        4. Focuses native entry widget and verifies focus.
        5. Automatically triggers Wispr Flow.
        6. Transitions state to WAITING_FOR_TRANSCRIPT.
        7. Starts 30-second overall safety session timeout.
        """
        with self._lock:
            if self._is_active:
                return
            self._is_active = True
            self.wake_timestamp = time.time()
            self.last_transcript_text = ""

        logger.info(f"[ASSISTANT] WAKE_DETECTED: Ctrl+Alt+A at {self.wake_timestamp:.3f}")
        logger.info("[VOICE] SESSION_STARTED")

        if self.state_callback:
            self.state_callback("LISTENING")

        self.initial_clipboard_text = self._read_current_clipboard()
        self.record_foreground_window()

        if self.root:
            self.root.after(0, self._prepare_and_focus_bridge)

        # 30-Second Overall Safety Session Timeout
        if self._overall_safety_timer:
            self._overall_safety_timer.cancel()
        self._overall_safety_timer = threading.Timer(
            OVERALL_SAFETY_TIMEOUT_SECONDS,
            self._handle_overall_safety_timeout
        )
        self._overall_safety_timer.daemon = True
        self._overall_safety_timer.start()

    def _prepare_and_focus_bridge(self):
        """Clears, shows, and focuses input entry window, verifying focus state."""
        if not self.root or not self.entry:
            return

        logger.info("[INPUT_BRIDGE] CLEARED")
        logger.info("[INPUT_BRIDGE] FOCUS_REQUESTED")

        self.entry.delete(0, tk.END)
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.entry.focus_set()

        # Verify focus
        focused_widget = self.root.focus_get()
        if focused_widget == self.entry:
            logger.info("[INPUT_BRIDGE] FOCUS_CONFIRMED")
        else:
            logger.warning(f"[INPUT_BRIDGE] FOCUS_LOST: Focused widget is {focused_widget}")

        # Automatically trigger Wispr Flow
        threading.Thread(target=send_wispr_shortcut, daemon=True).start()

        if self.state_callback:
            self.state_callback("WAITING_FOR_TRANSCRIPT")

        logger.info("[INPUT_BRIDGE] WAITING_FOR_TRANSCRIPT")

    def _hide_window(self):
        """Hides the entry window."""
        if not self.root or not self.entry:
            return
        self.entry.delete(0, tk.END)
        self.root.withdraw()

    def _on_key_typed(self, event=None):
        """Triggered when keys are typed into entry widget."""
        if not self._is_active:
            return
        
        if event and event.keysym in ("Return", "Escape", "Control_L", "Control_R", "Alt_L", "Alt_R", "Shift_L", "Shift_R"):
            return

        if self.entry:
            text = self.entry.get().strip()
            if text:
                self._on_text_updated(text, source="FOCUSED_ENTRY")

    def _on_return_pressed(self, event=None):
        """Triggered when Return key is pressed."""
        if not self.entry:
            return
        text = self.entry.get().strip()
        if text:
            logger.info("[INPUT_BRIDGE] Return key pressed. Finalizing transcript immediately...")
            self._finalize_speech_transcript(text)

    def _on_text_updated(self, text: str, source: str):
        """
        Invoked whenever transcript text arrives or updates in the bridge.
        Starts or resets the 2.0-second speech inactivity timer.
        """
        if not self._is_active or not text:
            return

        clean_text = text.strip()
        if clean_text == self.last_transcript_text:
            return

        self.last_transcript_text = clean_text

        logger.info(f'[INPUT_BRIDGE] TEXT_CHANGED: "{clean_text}"')
        logger.info(f'[WISPR] TRANSCRIPT_RECEIVED: "{clean_text}"')
        logger.info("[VOICE] SPEECH_ACTIVITY_DETECTED")

        # Start / Reset the 2.0-second inactivity timer
        if self._inactivity_timer:
            self._inactivity_timer.cancel()
            logger.info("[VOICE] INACTIVITY_TIMER_RESET")

        logger.info(f"[VOICE] INACTIVITY_TIMER_STARTED: {SPEECH_INACTIVITY_TIMEOUT_SECONDS} seconds")
        self._inactivity_timer = threading.Timer(
            SPEECH_INACTIVITY_TIMEOUT_SECONDS,
            lambda: self._on_inactivity_timer_expired(clean_text)
        )
        self._inactivity_timer.daemon = True
        self._inactivity_timer.start()

    def _on_inactivity_timer_expired(self, text_to_finalize: str):
        """
        Triggered when 2.0 continuous seconds pass with no new speech/input.
        Finalizes the speech transcript and sends it to the command processor.
        """
        if not self._is_active:
            return

        logger.info("[VOICE] SPEECH_END_CONFIRMED")
        self._finalize_speech_transcript(text_to_finalize)

    def _finalize_speech_transcript(self, text: str):
        """
        Finalizes transcript, applies deduplication, restores focus, and invokes command processor.
        """
        clean_text = text.strip()
        now = time.time()

        # Deduplication check
        if clean_text.lower() == self.last_finalized_text.lower() and (now - self.last_finalized_time) < 1.5:
            logger.info(f'[INPUT_BRIDGE] Duplicate transcript event ignored: "{clean_text}"')
            return

        self.last_finalized_text = clean_text
        self.last_finalized_time = now

        logger.info(f'[VOICE] FINAL_TRANSCRIPT: "{clean_text}"')

        self._close_bridge_session(text=clean_text)

        if self.state_callback:
            self.state_callback("PROCESSING")

        logger.info(f'[COMMAND_PROCESSOR] INPUT: "{clean_text}"')
        if self.command_callback:
            self.command_callback(clean_text)

    def _on_cancel(self, event=None):
        """Cancels activation session."""
        logger.info("[INPUT_BRIDGE] Session cancelled by user.")
        self._close_bridge_session(text=None)

    def _read_current_clipboard(self) -> Optional[str]:
        if not PYWIN32_AVAILABLE:
            return None
        try:
            win32clipboard.OpenClipboard()
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                win32clipboard.CloseClipboard()
                if data and isinstance(data, str):
                    return data.strip()
            win32clipboard.CloseClipboard()
        except Exception:
            pass
        return None

    _read_clipboard_fallback = _read_current_clipboard

    def _handle_overall_safety_timeout(self):
        """Handles 30-second overall session timeout if no transcript was finalized."""
        if not self._is_active:
            return

        logger.info("[VOICE] SESSION_TIMEOUT: 30-second overall safety timeout reached.")

        # Check if entry currently has text
        text = ""
        if self.entry and self.root:
            text = self.entry.get().strip()

        if text:
            logger.info(f"[INPUT_BRIDGE] Finalizing remaining entry text on timeout: '{text}'")
            self._finalize_speech_transcript(text)
            return

        logger.info("[VOICE] NO_TRANSCRIPT_RECEIVED")
        self._close_bridge_session(text=None)

    _handle_timeout = _handle_overall_safety_timeout

    def _close_bridge_session(self, text: Optional[str]):
        """Cleans up bridge session state, hides UI, and restores window focus."""
        with self._lock:
            if not self._is_active:
                return
            self._is_active = False

        if self._overall_safety_timer:
            self._overall_safety_timer.cancel()
            self._overall_safety_timer = None

        if self._inactivity_timer:
            self._inactivity_timer.cancel()
            self._inactivity_timer = None

        if self.root:
            self.root.after(0, self._hide_window)

        # Restore previous window focus
        if PYWIN32_AVAILABLE:
            time.sleep(RESTORE_FOCUS_DELAY_MS / 1000.0)
            self.restore_previous_window_focus()

        if not text or not text.strip():
            logger.info("[INPUT_BRIDGE] Resetting assistant state to READY.")
            if self.state_callback:
                self.state_callback("READY")

    def inject_command(self, text: str):
        """
        Preserved 100% unchanged manual command injection for test mode.
        """
        logger.info("[ASSISTANT] WAKE_DETECTED: Manual Inject Test Command")
        logger.info(f'[WISPR] TRANSCRIPT_RECEIVED: "{text}" (Source: INJECT_TEST_COMMAND)')
        logger.info(f'[VOICE] FINAL_TRANSCRIPT: "{text}"')
        if self.state_callback:
            self.state_callback("PROCESSING")
        logger.info(f'[COMMAND_PROCESSOR] INPUT: "{text}"')
        if self.command_callback:
            self.command_callback(text)

    def stop(self):
        """Stops background threads and cleans up resources."""
        if self.clipboard_listener:
            self.clipboard_listener.stop()
