"""
Windows Actions module for DesktopAssistant.
Provides safe, deterministic handlers for opening standard Windows applications.
Does NOT execute arbitrary shell commands.
"""

import os
import sys
import time
import shutil
import urllib.parse
import webbrowser
import subprocess
import logging
import ctypes
from ctypes import wintypes
from typing import Tuple, Optional

logger = logging.getLogger("DesktopAssistant.WindowsActions")

try:
    import win32gui
    import win32process
    import win32api
    import win32con
    from pynput.keyboard import Controller, Key
    PYWIN32_AVAILABLE = True
except Exception:
    PYWIN32_AVAILABLE = False

# Mapping of normalized action keywords to safe launch targets/commands
SAFE_APP_TARGETS = {
    "chrome": {
        "spoken": "Chrome",
        "targets": ["chrome.exe", r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]
    },
    "whatsapp": {
        "spoken": "WhatsApp",
        "protocol": "whatsapp:",
        "targets": ["whatsapp.exe"]
    },
    "file_explorer": {
        "spoken": "File Explorer",
        "targets": ["explorer.exe"]
    },
    "calculator": {
        "spoken": "Calculator",
        "targets": ["calc.exe"]
    },
    "settings": {
        "spoken": "Settings",
        "protocol": "ms-settings:"
    },
    "spotify": {
        "spoken": "Spotify",
        "protocol": "spotify:",
        "targets": [
            os.path.expanduser(r"~\AppData\Roaming\Spotify\Spotify.exe"),
            os.path.expanduser(r"~\AppData\Local\Microsoft\WindowsApps\spotify.exe"),
            os.path.expanduser(r"~\AppData\Local\Spotify\Spotify.exe"),
            r"C:\Program Files\Spotify\Spotify.exe",
            r"C:\Program Files (x86)\Spotify\Spotify.exe",
            "spotify.exe"
        ]
    }
}


def launch_windows_action(action_key: str) -> Tuple[bool, str]:
    """
    Safely launches a recognized Windows application or setting URI.
    
    Args:
        action_key: Key identifying target application in SAFE_APP_TARGETS.
        
    Returns:
        (success: bool, response_message: str)
    """
    if action_key not in SAFE_APP_TARGETS:
        logger.error(f"Attempted to execute unapproved action key: '{action_key}'")
        return False, "Sorry, that application is not authorized for launch."

    app_info = SAFE_APP_TARGETS[action_key]
    spoken_name = app_info["spoken"]

    # Try URI protocol if specified (e.g. ms-settings: or spotify:)
    if "protocol" in app_info:
        try:
            logger.info(f"Opening URI protocol: {app_info['protocol']}")
            os.startfile(app_info["protocol"])
            return True, f"Opening {spoken_name}."
        except Exception as e:
            logger.warning(f"URI protocol launch failed for {action_key}: {e}")

    # Try explicit target executables
    if "targets" in app_info:
        for target in app_info["targets"]:
            try:
                if os.path.isabs(target) and not os.path.exists(target):
                    continue
                logger.info(f"Launching executable target: {target}")
                os.startfile(target)
                return True, f"Opening {spoken_name}."
            except Exception as e:
                logger.debug(f"Target '{target}' launch failed: {e}")

    # Fallback to subprocess.Popen with shell=False for standard PATH binaries
    if "targets" in app_info and app_info["targets"]:
        fallback_exe = app_info["targets"][0]
        try:
            subprocess.Popen([fallback_exe], shell=False)
            return True, f"Opening {spoken_name}."
        except Exception as e:
            logger.error(f"Fallback launch failed for {fallback_exe}: {e}")

    return False, f"Sorry, could not open {spoken_name}."


def match_and_execute_action(text: str) -> Tuple[bool, Optional[str], str, bool]:
    """
    Analyzes input text to identify and execute authorized application launch intents.
    
    Returns:
        (is_action: bool, action_key: Optional[str], response_message: str, success: bool)
    """
    lower = text.lower().strip()

    intents = [
        (["open chrome", "launch chrome", "start chrome", "google chrome"], "chrome"),
        (["open whatsapp", "launch whatsapp", "start whatsapp"], "whatsapp"),
        (["open files", "open file explorer", "launch file explorer", "open explorer", "launch files"], "file_explorer"),
        (["open calculator", "launch calculator", "start calculator"], "calculator"),
        (["open settings", "launch settings", "start settings", "open windows settings"], "settings"),
        (["open spotify", "launch spotify", "start spotify", "open spotify app"], "spotify"),
    ]

    for phrases, key in intents:
        if any(phrase in lower for phrase in phrases):
            success, msg = launch_windows_action(key)
            return True, key, msg, success

    return False, None, "", False


def execute_youtube_search(query: str) -> Tuple[bool, str]:
    """
    URL-encodes search query and opens YouTube search results in default browser.
    """
    if not query or not query.strip():
        return False, "Sorry, I could not determine what to search on YouTube."

    clean_query = query.strip()
    try:
        encoded_query = urllib.parse.quote_plus(clean_query)
        url = f"https://www.youtube.com/results?search_query={encoded_query}"
        logger.info(f"[SEARCH_YOUTUBE] Opening YouTube search URL in default browser: '{url}'")
        opened = webbrowser.open(url)
        if opened:
            return True, f"Searching YouTube for {clean_query}."
        else:
            return False, "Sorry, the YouTube search could not be opened."
    except Exception as e:
        logger.error(f"[SEARCH_YOUTUBE] Error opening YouTube search URL: {e}")
        return False, "Sorry, the YouTube search could not be opened."


def execute_open_chatgpt() -> Tuple[bool, str]:
    """
    Opens https://chatgpt.com/ in default browser.
    """
    try:
        url = "https://chatgpt.com/"
        logger.info(f"[OPEN_CHATGPT] Opening ChatGPT URL in default browser: '{url}'")
        opened = webbrowser.open(url)
        if opened:
            return True, "Opening ChatGPT."
        else:
            return False, "Sorry, ChatGPT could not be opened."
    except Exception as e:
        logger.error(f"[OPEN_CHATGPT] Error opening ChatGPT URL: {e}")
        return False, "Sorry, ChatGPT could not be opened."


def _focus_chatgpt_chrome_window() -> Optional[int]:
    """Finds and brings Chrome or default browser window running ChatGPT to the foreground."""
    if not PYWIN32_AVAILABLE:
        return None
    try:
        user32 = ctypes.windll.user32
        import psutil

        chrome_pids = set()
        for p in psutil.process_iter(['pid', 'name']):
            try:
                pname = p.info['name'].lower() if p.info['name'] else ""
                if any(b in pname for b in ['chrome', 'msedge', 'brave', 'firefox', 'opera']):
                    chrome_pids.add(p.info['pid'])
            except Exception:
                pass

        found_hwnds = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def enum_cb(h, param):
            try:
                if user32.IsWindowVisible(h):
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                    if not chrome_pids or pid.value in chrome_pids:
                        title = win32gui.GetWindowText(h)
                        cls = win32gui.GetClassName(h)
                        if cls in ["Chrome_WidgetWin_1", "MozillaWindowClass"] or "chatgpt" in title.lower() or "chrome" in title.lower():
                            found_hwnds.append((h, title))
            except Exception:
                pass
            return True

        cb = WNDENUMPROC(enum_cb)
        user32.EnumWindows(cb, 0)

        target_hwnd = None
        for h, t in found_hwnds:
            if "chatgpt" in t.lower():
                target_hwnd = h
                break
        if not target_hwnd and found_hwnds:
            for h, t in found_hwnds:
                if any(k in t.lower() for k in ["chrome", "google", "new tab"]):
                    target_hwnd = h
                    break
            if not target_hwnd:
                target_hwnd = found_hwnds[0][0]

        if target_hwnd and win32gui.IsWindow(target_hwnd):
            if win32gui.IsIconic(target_hwnd):
                win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
            else:
                win32gui.ShowWindow(target_hwnd, win32con.SW_SHOW)

            fore_hwnd = win32gui.GetForegroundWindow()
            curr_thread = win32api.GetCurrentThreadId()
            fore_thread, _ = win32process.GetWindowThreadProcessId(fore_hwnd) if fore_hwnd else (0, 0)
            target_thread, _ = win32process.GetWindowThreadProcessId(target_hwnd)

            try:
                user32.AllowSetForegroundWindow(-1)
            except Exception:
                pass

            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 2, 0)

            if fore_thread != 0 and fore_thread != curr_thread:
                win32process.AttachThreadInput(curr_thread, fore_thread, True)
                win32process.AttachThreadInput(curr_thread, target_thread, True)
                try:
                    win32gui.SetForegroundWindow(target_hwnd)
                    win32gui.BringWindowToTop(target_hwnd)
                except Exception:
                    pass
                win32process.AttachThreadInput(curr_thread, target_thread, False)
                win32process.AttachThreadInput(curr_thread, fore_thread, False)
            else:
                try:
                    win32gui.SetForegroundWindow(target_hwnd)
                    win32gui.BringWindowToTop(target_hwnd)
                except Exception:
                    pass
            time.sleep(0.3)
            return target_hwnd
    except Exception as e:
        logger.warning(f"[ASK_CHATGPT] Error focusing Chrome window: {e}")
    return None


def _try_uia_focus_chatgpt_input(hwnd: Optional[int] = None) -> bool:
    """Attempts to locate and focus the ChatGPT message input box using Windows UI Automation."""
    if not PYWIN32_AVAILABLE:
        return False
    try:
        import comtypes.client
        UIAutomationClient = comtypes.client.GetModule('UIAutomationCore.dll')
        uia = comtypes.client.CreateObject(UIAutomationClient.CUIAutomation, interface=UIAutomationClient.IUIAutomation)

        target_elem = None
        if hwnd and win32gui.IsWindow(hwnd):
            try:
                target_elem = uia.ElementFromHandle(hwnd)
            except Exception:
                pass
        if not target_elem:
            target_elem = uia.GetRootElement()

        # 1. Look for element with AutomationId 'prompt-textarea'
        cond_id = uia.CreatePropertyCondition(UIAutomationClient.UIA_AutomationIdPropertyId, "prompt-textarea")
        found = target_elem.FindFirst(UIAutomationClient.TreeScope_Subtree, cond_id)
        if found:
            try:
                found.SetFocus()
                return True
            except Exception:
                pass

        # 2. Look for Edit / Document / Group controls with relevant name or help text
        for ctrl_type in [50004, 50030, 50026]:
            cond = uia.CreatePropertyCondition(UIAutomationClient.UIA_ControlTypePropertyId, ctrl_type)
            elems = target_elem.FindAll(UIAutomationClient.TreeScope_Subtree, cond)
            for i in range(elems.Length):
                item = elems.GetElement(i)
                name = (item.CurrentName or "").lower()
                help_text = (item.CurrentHelpText or "").lower()
                auto_id = (item.CurrentAutomationId or "").lower()
                if any(k in name or k in help_text or k in auto_id for k in ["prompt", "message", "ask", "chatgpt", "send a message"]):
                    try:
                        item.SetFocus()
                        return True
                    except Exception:
                        pass
    except Exception as e:
        logger.debug(f"[ASK_CHATGPT] UIA focus attempt exception: {e}")
    return False


def _find_and_focus_chatgpt_input_box(max_wait_seconds: float = 6.0) -> bool:
    """Waits for ChatGPT to load in Chrome and locates/focuses the input message box."""
    start_time = time.time()
    chrome_hwnd = _focus_chatgpt_chrome_window()

    while time.time() - start_time < max_wait_seconds:
        if _try_uia_focus_chatgpt_input(chrome_hwnd):
            logger.info("[ASK_CHATGPT] ChatGPT input box located and focused via UIA.")
            return True

        if PYWIN32_AVAILABLE:
            try:
                fore_hwnd = win32gui.GetForegroundWindow()
                if fore_hwnd and win32gui.IsWindow(fore_hwnd):
                    title = win32gui.GetWindowText(fore_hwnd).lower()
                    if any(k in title for k in ["chatgpt", "chrome", "google", "new tab"]):
                        if _try_uia_focus_chatgpt_input(fore_hwnd):
                            logger.info(f"[ASK_CHATGPT] ChatGPT input box located via foreground window ('{title}').")
                            return True
            except Exception:
                pass

        time.sleep(0.5)

    return False


def _submit_chatgpt_query():
    """Submits the query in ChatGPT by sending Enter or invoking UIA Send button."""
    try:
        if PYWIN32_AVAILABLE:
            try:
                import comtypes.client
                UIAutomationClient = comtypes.client.GetModule('UIAutomationCore.dll')
                uia = comtypes.client.CreateObject(UIAutomationClient.CUIAutomation, interface=UIAutomationClient.IUIAutomation)
                root = uia.GetRootElement()

                cond_btn = uia.CreatePropertyCondition(UIAutomationClient.UIA_ControlTypePropertyId, 50000)
                btns = root.FindAll(UIAutomationClient.TreeScope_Subtree, cond_btn)
                for i in range(btns.Length):
                    btn = btns.GetElement(i)
                    name = (btn.CurrentName or "").lower()
                    auto_id = (btn.CurrentAutomationId or "").lower()
                    if "send" in name or "send" in auto_id:
                        pattern = btn.GetCurrentPattern(UIAutomationClient.UIA_InvokePatternId)
                        if pattern:
                            pattern.QueryInterface(UIAutomationClient.IUIAutomationInvokePattern).Invoke()
                            time.sleep(0.2)
                            return
            except Exception:
                pass

        keyboard = Controller()
        keyboard.press(Key.enter)
        keyboard.release(Key.enter)
        time.sleep(0.2)
    except Exception as e:
        logger.warning(f"[ASK_CHATGPT] Error submitting ChatGPT query: {e}")


def execute_ask_chatgpt(query: str) -> Tuple[bool, str]:
    """
    Opens https://chatgpt.com/?q=... in default browser (Chrome), waits for input box,
    types/submits the query, and verifies browser navigation.
    """
    if not query or not query.strip():
        return False, "Sorry, I could not determine what to ask ChatGPT."

    clean_query = query.strip()
    encoded_query = urllib.parse.quote(clean_query)
    url = f"https://chatgpt.com/?q={encoded_query}"

    try:
        logger.info(f"[ASK_CHATGPT] Opening ChatGPT URL in default browser: '{url}'")
        opened = webbrowser.open(url)
        if not opened:
            logger.error("[ASK_CHATGPT] Browser launch failed for ChatGPT.")
            return False, "Sorry, ChatGPT could not be opened."

        time.sleep(0.8)

        input_found = _find_and_focus_chatgpt_input_box(max_wait_seconds=6.0)
        if input_found:
            logger.info(f"[ASK_CHATGPT] Typing query into ChatGPT: '{clean_query}'")
            type_text_via_clipboard(clean_query)
            time.sleep(0.4)
            logger.info("[ASK_CHATGPT] Submitting query to ChatGPT...")
            _submit_chatgpt_query()
        else:
            logger.info(f"[ASK_CHATGPT] ChatGPT search launched via direct URL query: '{clean_query}'")

        return True, f"Asking ChatGPT: {clean_query}"

    except Exception as e:
        logger.error(f"[ASK_CHATGPT] Error executing ChatGPT search: {e}")
        return False, "Sorry, ChatGPT search could not be loaded."



def _focus_spotify_window_and_play():
    """Focuses the Spotify Desktop app window and sends Enter/Space/MediaPlay keys to start track playback."""
    if not PYWIN32_AVAILABLE:
        return
    try:
        user32 = ctypes.windll.user32
        
        import psutil
        spotify_pids = set(p.pid for p in psutil.process_iter() if 'spotify' in p.name().lower())
        found_hwnds = []

        def enum_cb(h, param):
            try:
                _, pid = win32process.GetWindowThreadProcessId(h)
                if pid in spotify_pids and win32gui.IsWindowVisible(h):
                    title = win32gui.GetWindowText(h)
                    cls = win32gui.GetClassName(h)
                    if cls == "Chrome_WidgetWin_1" or "spotify" in title.lower():
                        found_hwnds.append((h, title, cls))
            except Exception:
                pass
            return 1

        try:
            win32gui.EnumWindows(enum_cb, 0)
        except Exception:
            pass

        hwnd = None
        for h, title, cls in found_hwnds:
            if title and "spotify" in title.lower():
                hwnd = h
                break
        if not hwnd and found_hwnds:
            hwnd = found_hwnds[0][0]

        if hwnd and win32gui.IsWindow(hwnd):
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            else:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)

            fore_hwnd = win32gui.GetForegroundWindow()
            curr_thread = win32api.GetCurrentThreadId()
            fore_thread, _ = win32process.GetWindowThreadProcessId(fore_hwnd) if fore_hwnd else (0, 0)
            target_thread, _ = win32process.GetWindowThreadProcessId(hwnd)

            try:
                user32.AllowSetForegroundWindow(-1)
            except Exception:
                pass

            # Alt key tap trick
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 2, 0)

            if fore_thread != 0 and fore_thread != curr_thread:
                win32process.AttachThreadInput(curr_thread, fore_thread, True)
                win32process.AttachThreadInput(curr_thread, target_thread, True)
                try:
                    win32gui.SetForegroundWindow(hwnd)
                    win32gui.BringWindowToTop(hwnd)
                except Exception:
                    pass
                win32process.AttachThreadInput(curr_thread, target_thread, False)
                win32process.AttachThreadInput(curr_thread, fore_thread, False)
            else:
                try:
                    win32gui.SetForegroundWindow(hwnd)
                    win32gui.BringWindowToTop(hwnd)
                except Exception:
                    pass

            time.sleep(0.5)

        # Send playback keys sequence (Enter to select top track result, Space, and Media Play/Pause)
        keyboard = Controller()
        keyboard.press(Key.enter)
        keyboard.release(Key.enter)
        time.sleep(0.3)

        keyboard.press(Key.space)
        keyboard.release(Key.space)
        time.sleep(0.2)

        # VK_MEDIA_PLAY_PAUSE = 0xB3
        user32.keybd_event(0xB3, 0, 0, 0)
        user32.keybd_event(0xB3, 0, 2, 0)
        time.sleep(0.2)

    except Exception as e:
        logger.warning(f"Spotify window focus/play key simulation error: {e}")


def execute_play_spotify_song(song: str, artist: Optional[str] = None) -> Tuple[bool, str]:
    """
    Searches for and starts playback of a song in the installed Spotify Desktop Application.
    """
    if not song or not song.strip():
        return False, "Sorry, I could not understand which song to play."

    clean_song = song.strip()
    clean_artist = artist.strip() if artist else None

    # Check for installed Spotify desktop executable
    spotify_targets = [
        os.path.expanduser(r"~\AppData\Roaming\Spotify\Spotify.exe"),
        os.path.expanduser(r"~\AppData\Local\Microsoft\WindowsApps\spotify.exe"),
        os.path.expanduser(r"~\AppData\Local\Spotify\Spotify.exe"),
        r"C:\Program Files\Spotify\Spotify.exe",
        r"C:\Program Files (x86)\Spotify\Spotify.exe",
    ]
    spotify_exe = None
    for target in spotify_targets:
        if os.path.exists(target):
            spotify_exe = target
            break

    if not spotify_exe:
        which_path = shutil.which("spotify")
        if which_path:
            spotify_exe = which_path

    if not spotify_exe:
        logger.error("Spotify desktop application executable not found.")
        return False, "Sorry, Spotify desktop application could not be opened because it is not installed."

    try:
        # Check if Spotify is currently running
        spotify_running = False
        try:
            import psutil
            for proc in psutil.process_iter(['name']):
                if proc.info['name'] and proc.info['name'].lower() == "spotify.exe":
                    spotify_running = True
                    break
        except Exception:
            pass

        if not spotify_running:
            logger.info(f"[PLAY_SPOTIFY_SONG] Launching Spotify desktop app: '{spotify_exe}'")
            subprocess.Popen([spotify_exe], shell=False)
            time.sleep(2.5)

        # Prefer track search syntax to prioritize song/track results over albums/playlists
        if clean_artist:
            search_term = f"{clean_song} {clean_artist}"
        else:
            search_term = f"track:{clean_song}"

        encoded = urllib.parse.quote(search_term)
        uri = f"spotify:search:{encoded}"

        logger.info(f"[PLAY_SPOTIFY_SONG] Executing Spotify URI search: '{uri}'")
        os.startfile(uri)
        time.sleep(1.5)

        # Focus Spotify Desktop app & initiate playback
        _focus_spotify_window_and_play()

        song_display = clean_song.title()
        if clean_artist:
            artist_display = clean_artist.title()
            return True, f"Playing {song_display} by {artist_display} on Spotify."
        else:
            return True, f"Playing {song_display} on Spotify."

    except Exception as e:
        logger.error(f"[PLAY_SPOTIFY_SONG] Failed to execute Spotify song playback: {e}")
        return False, "Sorry, Spotify could not be opened or the song could not be played."


def type_text_via_clipboard(text: str):
    """Pastes text using Windows clipboard and Ctrl+V to preserve all characters and punctuation."""
    if not PYWIN32_AVAILABLE:
        keyboard = Controller()
        keyboard.type(text)
        return

    try:
        import win32clipboard

        old_text = None
        try:
            win32clipboard.OpenClipboard()
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                old_text = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
        except Exception:
            pass

        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        win32clipboard.CloseClipboard()

        time.sleep(0.1)

        keyboard = Controller()
        keyboard.press(Key.ctrl)
        keyboard.press('v')
        keyboard.release('v')
        keyboard.release(Key.ctrl)

        time.sleep(0.2)

        if old_text is not None:
            try:
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(old_text, win32clipboard.CF_UNICODETEXT)
                win32clipboard.CloseClipboard()
            except Exception:
                pass
    except Exception:
        keyboard = Controller()
        keyboard.type(text)


def _focus_whatsapp_window():
    """Focuses the WhatsApp Desktop application window."""
    if not PYWIN32_AVAILABLE:
        return
    try:
        user32 = ctypes.windll.user32
        import psutil
        wa_pids = set(p.pid for p in psutil.process_iter() if 'whatsapp' in p.name().lower())

        found_hwnds = []
        def enum_cb(h, param):
            try:
                _, pid = win32process.GetWindowThreadProcessId(h)
                if pid in wa_pids and win32gui.IsWindowVisible(h):
                    title = win32gui.GetWindowText(h)
                    cls = win32gui.GetClassName(h)
                    if "whatsapp" in title.lower() or "whatsapp" in cls.lower():
                        found_hwnds.append((h, title, cls))
            except Exception:
                pass
            return 1

        try:
            win32gui.EnumWindows(enum_cb, 0)
        except Exception:
            pass

        if not found_hwnds:
            def enum_cb_all(h, param):
                if win32gui.IsWindowVisible(h):
                    t = win32gui.GetWindowText(h)
                    c = win32gui.GetClassName(h)
                    if "whatsapp" in t.lower() or "whatsapp" in c.lower():
                        found_hwnds.append((h, t, c))
                return 1
            try:
                win32gui.EnumWindows(enum_cb_all, 0)
            except Exception:
                pass

        hwnd = None
        for h, title, cls in found_hwnds:
            if title and "whatsapp" in title.lower():
                hwnd = h
                break
        if not hwnd and found_hwnds:
            hwnd = found_hwnds[0][0]

        if hwnd and win32gui.IsWindow(hwnd):
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            else:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)

            fore_hwnd = win32gui.GetForegroundWindow()
            curr_thread = win32api.GetCurrentThreadId()
            fore_thread, _ = win32process.GetWindowThreadProcessId(fore_hwnd) if fore_hwnd else (0, 0)
            target_thread, _ = win32process.GetWindowThreadProcessId(hwnd)

            try:
                user32.AllowSetForegroundWindow(-1)
            except Exception:
                pass

            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 2, 0)

            if fore_thread != 0 and fore_thread != curr_thread:
                win32process.AttachThreadInput(curr_thread, fore_thread, True)
                win32process.AttachThreadInput(curr_thread, target_thread, True)
                try:
                    win32gui.SetForegroundWindow(hwnd)
                    win32gui.BringWindowToTop(hwnd)
                except Exception:
                    pass
                win32process.AttachThreadInput(curr_thread, target_thread, False)
                win32process.AttachThreadInput(curr_thread, fore_thread, False)
            else:
                try:
                    win32gui.SetForegroundWindow(hwnd)
                    win32gui.BringWindowToTop(hwnd)
                except Exception:
                    pass

            time.sleep(0.4)
    except Exception as e:
        logger.warning(f"WhatsApp window focus error: {e}")


def execute_send_whatsapp_message(recipient: str, message: str) -> Tuple[bool, str]:
    """
    Opens WhatsApp Desktop, searches for recipient contact, opens chat view, and types message.
    CRITICAL: NEVER PRESSES ENTER OR CLICKS SEND! Leaves message drafted in compose box.
    """
    if not recipient or not recipient.strip():
        return False, "Sorry, I could not determine who to message on WhatsApp."
    if not message or not message.strip():
        return False, "Sorry, I could not determine what message to draft."

    clean_recipient = recipient.strip()
    clean_message = message.strip()

    try:
        logger.info(f"[SEND_WHATSAPP_MESSAGE] Opening WhatsApp Desktop application...")
        # Launch or bring WhatsApp to front
        success, _ = launch_windows_action("whatsapp")
        time.sleep(1.5)

        _focus_whatsapp_window()

        keyboard = Controller()

        # 1. Focus Search (Ctrl+F)
        keyboard.press(Key.ctrl)
        keyboard.press('f')
        keyboard.release('f')
        keyboard.release(Key.ctrl)
        time.sleep(0.3)

        # 2. Type recipient contact name
        type_text_via_clipboard(clean_recipient)
        time.sleep(0.8)

        # 3. Open contact chat (Enter)
        keyboard.press(Key.enter)
        keyboard.release(Key.enter)
        time.sleep(0.5)

        # 4. Type message into compose box (CRITICAL: NEVER PRESS ENTER / SEND!)
        type_text_via_clipboard(clean_message)

        recipient_display = clean_recipient.title()
        return True, f"Message drafted for {recipient_display}. Please review and send it."

    except Exception as e:
        logger.error(f"[SEND_WHATSAPP_MESSAGE] Error drafting WhatsApp message: {e}")
        return False, "Sorry, WhatsApp could not be opened or the message could not be drafted."

