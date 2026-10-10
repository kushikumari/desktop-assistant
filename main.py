"""
Main Application Entry point for DesktopAssistant.
Manages system tray icon, single-instance enforcement, global hotkeys,
and application state transitions.
"""

import os
import sys
import time
import threading
import logging
import tkinter as tk
from tkinter import simpledialog
from typing import Optional

from PIL import Image, ImageDraw

from config import (
    APP_NAME,
    APP_VERSION,
    SINGLE_INSTANCE_MUTEX,
    AssistantState,
    STATE_COLORS,
    ACTIVATION_HOTKEY,
    ERROR_RECOVERY_DELAY_SECONDS,
    setup_logging,
)
from voice_output import VoiceOutput
from command_processor import process_command, CommandResult
from input_bridge import WisprInputBridge
from startup_manager import is_startup_enabled, set_startup_enabled, toggle_startup

# Import Windows specific packages
try:
    import win32api
    import win32event
    import winerror
    PYWIN32_AVAILABLE = True
except ImportError:
    PYWIN32_AVAILABLE = False

try:
    import pystray
    PYSTRAY_AVAILABLE = True
except ImportError:
    PYSTRAY_AVAILABLE = False

try:
    from pynput import keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

logger = setup_logging(verbose=True)


def create_status_icon_image(state: AssistantState) -> Image.Image:
    """
    Dynamically generates a 64x64 status icon image for the system tray using Pillow.
    Uses distinctive colors and crisp graphical badges.
    """
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Outer circle background (dark slate blue)
    draw.ellipse((4, 4, size - 4, size - 4), fill=(15, 23, 42, 255), outline=(71, 85, 105, 255), width=2)

    # Inner status badge circle
    color_rgb = STATE_COLORS.get(state, (16, 185, 129))
    draw.ellipse((16, 16, size - 16, size - 16), fill=color_rgb + (255,))

    # Center white dot indicator
    draw.ellipse((26, 26, size - 26, size - 26), fill=(255, 255, 255, 240))
    
    return img


class SingleInstanceLock:
    """Enforces single-instance execution using Windows Mutex."""

    def __init__(self, mutex_name: str = SINGLE_INSTANCE_MUTEX):
        self.mutex_name = mutex_name
        self.mutex = None
        self.already_running = False

    def acquire(self) -> bool:
        if not PYWIN32_AVAILABLE:
            return True

        try:
            self.mutex = win32event.CreateMutex(None, False, self.mutex_name)
            last_error = win32api.GetLastError()
            if last_error == winerror.ERROR_ALREADY_EXISTS:
                self.already_running = True
                return False
            return True
        except Exception as e:
            logger.warning(f"Could not check single instance mutex: {e}")
            return True

    def release(self):
        if PYWIN32_AVAILABLE and self.mutex:
            try:
                win32api.CloseHandle(self.mutex)
                self.mutex = None
            except Exception:
                pass


class DesktopAssistantApp:
    """
    Main DesktopAssistant application controller class.
    Coordinates System Tray, Hotkeys, Input Bridge, Command Processing, and TTS.
    """

    def __init__(self):
        self.state = AssistantState.READY
        self.single_instance_lock = SingleInstanceLock()
        
        # Modules
        self.voice_output: Optional[VoiceOutput] = None
        self.input_bridge: Optional[WisprInputBridge] = None
        self.tray_icon: Optional[pystray.Icon] = None
        self.hotkey_listener: Optional[keyboard.GlobalHotKeys] = None
        
        # Timers
        self._recovery_timer: Optional[threading.Timer] = None
        self._watchdog_timer: Optional[threading.Timer] = None
        
        # Main UI Root (Tkinter)
        self.tk_root: Optional[tk.Tk] = None
        self._is_running = False
        self._lock = threading.Lock()

    def set_state(self, new_state_name: str):
        """Updates internal state, system tray icon, and handles recovery/watchdog timers."""
        try:
            new_state = AssistantState[new_state_name.upper()]
        except KeyError:
            logger.warning(f"Unknown state string: {new_state_name}")
            return

        with self._lock:
            if self.state == new_state:
                return
            self.state = new_state
            logger.info(f"[ASSISTANT] {self.state.value}")

        # Cancel any active recovery/watchdog timer
        if self._recovery_timer:
            self._recovery_timer.cancel()
            self._recovery_timer = None
        if self._watchdog_timer:
            self._watchdog_timer.cancel()
            self._watchdog_timer = None

        # Handle ERROR state auto-recovery to READY
        if self.state == AssistantState.ERROR:
            logger.info(f"ERROR state entered. Scheduling auto-recovery to READY in {ERROR_RECOVERY_DELAY_SECONDS}s.")
            self._recovery_timer = threading.Timer(
                ERROR_RECOVERY_DELAY_SECONDS,
                lambda: self.set_state("READY")
            )
            self._recovery_timer.daemon = True
            self._recovery_timer.start()

        # Handle non-READY state watchdog (forces back to READY if stuck > 35s)
        elif self.state != AssistantState.READY:
            self._watchdog_timer = threading.Timer(
                35.0,
                self._handle_state_watchdog_timeout
            )
            self._watchdog_timer.daemon = True
            self._watchdog_timer.start()

        # Update System Tray UI
        if self.tray_icon and PYSTRAY_AVAILABLE:
            try:
                new_image = create_status_icon_image(self.state)
                self.tray_icon.icon = new_image
                self.tray_icon.title = f"{APP_NAME} - {self.state.value}"
                self.tray_icon.update_menu()
            except Exception as e:
                logger.error(f"Failed to update tray icon: {e}")

    def _handle_state_watchdog_timeout(self):
        """Safety watchdog callback: resets assistant state to READY if stuck in active state."""
        with self._lock:
            if self.state == AssistantState.READY:
                return
            logger.warning(f"State watchdog triggered! Force resetting stuck state '{self.state.value}' to READY.")
        self.set_state("READY")

    def on_transcription_received(self, text: str):
        """Callback invoked when Wispr Input Bridge captures transcribed text."""
        logger.info(f'[COMMAND_PROCESSOR] Received transcription text from bridge: "{text}"')
        self.set_state("PROCESSING")

        # Process command through pipeline
        try:
            result: CommandResult = process_command(text)
            logger.info(f'[COMMAND_PROCESSOR] Intent="{result.intent}", Success={result.action_success}, Response="{result.response_text}"')

            if not result.action_success:
                self.set_state("ERROR")
            else:
                self.set_state("EXECUTING")

            # Speak response via TTS
            if self.voice_output:
                self.voice_output.speak(
                    result.response_text,
                    on_done=lambda: self._handle_post_command(result)
                )
            else:
                self._handle_post_command(result)
        except Exception as e:
            logger.error(f"Unhandled exception during command processing: {e}")
            self.set_state("ERROR")

    def _handle_post_command(self, result: CommandResult):
        """Handles completion of speech and clean exit if requested."""
        if result.should_exit:
            logger.info("Exit command requested. Shutting down DesktopAssistant...")
            time.sleep(0.5)
            self.shutdown()
        else:
            self.set_state("READY")

    def _on_hotkey_activated(self):
        """Callback invoked when global activation hotkey is pressed."""
        logger.info("Global activation hotkey pressed.")
        if self.input_bridge:
            self.input_bridge.activate()

    def inject_test_command(self):
        """Tray menu handler: open a prompt to inject a command manually."""
        def prompt_dialog():
            if not self.tk_root:
                return
            user_input = simpledialog.askstring(
                "Inject Test Command",
                "Enter voice/text command to simulate:",
                parent=self.tk_root
            )
            if user_input and user_input.strip():
                if self.input_bridge:
                    self.input_bridge.inject_command(user_input.strip())

        if self.tk_root:
            self.tk_root.after(0, prompt_dialog)

    def _on_toggle_startup(self, icon, item):
        new_val = not is_startup_enabled()
        set_startup_enabled(new_val)
        if self.tray_icon:
            self.tray_icon.update_menu()

    def setup_tray_menu(self) -> pystray.Menu:
        """Constructs the system tray context menu."""
        def get_status_text(item):
            return f"Status: {self.state.value}"

        return pystray.Menu(
            pystray.MenuItem(get_status_text, lambda item: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"Activate Voice Input ({ACTIVATION_HOTKEY})", lambda item: self._on_hotkey_activated()),
            pystray.MenuItem("Inject Command (Test Mode)...", lambda item: self.inject_test_command()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Launch on Windows Startup", self._on_toggle_startup, checked=lambda item: is_startup_enabled()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit Assistant", lambda item: self.shutdown())
        )

    def start_hotkey_listener(self):
        """Starts background listener for global activation hotkeys."""
        if not PYNPUT_AVAILABLE:
            logger.warning("pynput is not installed. Global hotkeys disabled.")
            return

        try:
            hotkey_map = {
                ACTIVATION_HOTKEY: self._on_hotkey_activated
            }
            self.hotkey_listener = keyboard.GlobalHotKeys(hotkey_map)
            self.hotkey_listener.start()
            logger.info(f"Global hotkey listener registered for '{ACTIVATION_HOTKEY}'.")
        except Exception as e:
            logger.error(f"Failed to register global hotkey: {e}")

    def run(self):
        """Main application lifecycle runner."""
        # 1. Single Instance Check
        if not self.single_instance_lock.acquire():
            logger.error("Another instance of DesktopAssistant is already running. Exiting.")
            print("DesktopAssistant is already running in the background.")
            sys.exit(0)

        self._is_running = True
        logger.info(f"Starting {APP_NAME} v{APP_VERSION}...")

        # 2. Initialize Voice Output (TTS)
        self.voice_output = VoiceOutput(state_callback=None)  # App manages state sequence explicitly
        self.voice_output.start()

        # 3. Speak startup notification
        self.voice_output.speak("Desktop Assistant is ready.")

        # 4. Initialize Tkinter Root Window (main loop host)
        self.tk_root = tk.Tk()
        self.tk_root.withdraw()

        # 5. Initialize Wispr Input Bridge
        self.input_bridge = WisprInputBridge(
            command_callback=self.on_transcription_received,
            state_callback=self.set_state
        )
        self.input_bridge.create_ui(self.tk_root)

        # 6. Start Global Hotkeys
        self.start_hotkey_listener()

        # 7. Start System Tray Icon in a background thread
        if PYSTRAY_AVAILABLE:
            initial_image = create_status_icon_image(self.state)
            self.tray_icon = pystray.Icon(
                APP_NAME,
                initial_image,
                title=f"{APP_NAME} - {self.state.value}",
                menu=self.setup_tray_menu()
            )
            tray_thread = threading.Thread(
                target=self.tray_icon.run,
                name="SystemTrayThread",
                daemon=True
            )
            tray_thread.start()
            logger.info("System tray icon started.")
        else:
            logger.warning("pystray is not installed. System tray icon disabled.")

        logger.info("DesktopAssistant is running in the background.")

        # 8. Start Tkinter Main GUI Loop
        try:
            self.tk_root.mainloop()
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received.")
        finally:
            self.shutdown()

    def shutdown(self):
        """Performs a clean shutdown of all application components."""
        with self._lock:
            if not self._is_running:
                return
            self._is_running = False

        logger.info("Shutting down DesktopAssistant...")

        if self._recovery_timer:
            self._recovery_timer.cancel()
        if self._watchdog_timer:
            self._watchdog_timer.cancel()

        if self.hotkey_listener:
            try:
                self.hotkey_listener.stop()
            except Exception:
                pass

        if self.input_bridge:
            try:
                self.input_bridge.stop()
            except Exception:
                pass

        if self.voice_output:
            try:
                self.voice_output.stop()
            except Exception:
                pass

        if self.tray_icon and PYSTRAY_AVAILABLE:
            try:
                self.tray_icon.stop()
            except Exception:
                pass

        self.single_instance_lock.release()

        if self.tk_root:
            try:
                self.tk_root.quit()
                self.tk_root.destroy()
            except Exception:
                pass

        logger.info("DesktopAssistant successfully stopped.")
        sys.exit(0)


def main():
    """CLI Entrypoint."""
    app = DesktopAssistantApp()
    app.run()


if __name__ == "__main__":
    main()
