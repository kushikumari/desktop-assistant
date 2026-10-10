"""
Startup Manager module for DesktopAssistant.
Provides per-user Windows Startup enable/disable registry management.
Uses HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.
"""

import sys
import os
import logging

try:
    import winreg
    WINREG_AVAILABLE = True
except ImportError:
    WINREG_AVAILABLE = False

logger = logging.getLogger("DesktopAssistant.StartupManager")

REG_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_APP_NAME = "DesktopAssistant"


def get_target_command() -> str:
    """Returns the formatted executable command line for startup registry."""
    if getattr(sys, 'frozen', False):
        # PyInstaller packaged executable path
        exe_path = os.path.abspath(sys.executable)
        return f'"{exe_path}"'
    else:
        # Python script execution path
        python_exe = os.path.abspath(sys.executable)
        script_path = os.path.abspath(sys.argv[0])
        return f'"{python_exe}" "{script_path}"'


def is_startup_enabled() -> bool:
    """
    Checks if DesktopAssistant is currently configured to run on Windows startup.
    
    Returns:
        bool: True if startup registry key exists, False otherwise.
    """
    if not WINREG_AVAILABLE:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, REG_APP_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.warning(f"Could not read startup registry key: {e}")
        return False


def set_startup_enabled(enable: bool) -> bool:
    """
    Enables or disables per-user Windows startup registration in registry.
    
    Args:
        enable: True to register for startup, False to unregister.
        
    Returns:
        bool: True if operation succeeded, False otherwise.
    """
    if not WINREG_AVAILABLE:
        logger.error("winreg module not available on this platform.")
        return False

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                cmd = get_target_command()
                winreg.SetValueEx(key, REG_APP_NAME, 0, winreg.REG_SZ, cmd)
                logger.info(f"Successfully enabled Windows startup registry entry: {cmd}")
            else:
                try:
                    winreg.DeleteValue(key, REG_APP_NAME)
                    logger.info("Successfully removed Windows startup registry entry.")
                except FileNotFoundError:
                    pass
            return True
    except Exception as e:
        logger.error(f"Failed to update startup registry setting (enable={enable}): {e}")
        return False


def toggle_startup() -> bool:
    """Toggles current Windows startup setting and returns new status."""
    current = is_startup_enabled()
    new_status = not current
    success = set_startup_enabled(new_status)
    return is_startup_enabled() if success else current
