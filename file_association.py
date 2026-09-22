from __future__ import annotations

import os
import sys
from pathlib import Path

PROGID = "FieldBookSync.Project"
EXTENSION = ".fbs"


def _notify_shell() -> None:
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
    except Exception:
        pass


def _built_exe(root: Path) -> Path | None:
    # Support both a packaged distribution folder and the source-tree build output.
    candidates = [
        root / "FieldBookSync.exe",
        root / "dist" / "FieldBookSync" / "FieldBookSync.exe",
    ]
    return next((p for p in candidates if p.exists()), None)


def _open_command(root: Path) -> str:
    exe = _built_exe(root)
    if exe:
        return f'"{exe}" "%1"'
    launcher = root / "run_windows.bat"
    return f'cmd.exe /d /c ""{launcher}" "%1""'


def register(root: Path) -> None:
    if os.name != "nt":
        raise RuntimeError(".fbs file association can only be registered on Windows.")
    import winreg
    base = r"Software\Classes"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\.fbs") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, PROGID)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + "\\" + PROGID) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "FieldBook Sync Project")
        winreg.SetValueEx(key, "FriendlyTypeName", 0, winreg.REG_SZ, "FieldBook Sync Project")
    exe = _built_exe(root)
    project_icon_candidates = [
        root / "project_icon.ico",
        root / "fieldbook_sync" / "static" / "project_icon.ico",
    ]
    project_icon = next((p for p in project_icon_candidates if p.exists()), None)
    icon = project_icon if project_icon else (exe if exe else root / "fieldbook_sync" / "static" / "favicon.ico")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + "\\" + PROGID + r"\DefaultIcon") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{icon}",0')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + "\\" + PROGID + r"\shell\open\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, _open_command(root))
    _notify_shell()


def unregister() -> None:
    if os.name != "nt":
        raise RuntimeError(".fbs file association can only be unregistered on Windows.")
    import winreg
    def delete_tree(parent, subkey: str) -> None:
        try:
            with winreg.OpenKey(parent, subkey, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                while True:
                    try:
                        child = winreg.EnumKey(key, 0)
                    except OSError:
                        break
                    delete_tree(parent, subkey + "\\" + child)
            winreg.DeleteKey(parent, subkey)
        except FileNotFoundError:
            pass
    delete_tree(winreg.HKEY_CURRENT_USER, "Software\\Classes\\" + PROGID)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.fbs", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            value, _ = winreg.QueryValueEx(key, "")
        if value == PROGID:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.fbs")
    except FileNotFoundError:
        pass
    _notify_shell()


def main() -> int:
    if os.name != "nt":
        print("This helper is only used on Windows.")
        return 1
    action = (sys.argv[1] if len(sys.argv) > 1 else "register").lower()
    root = Path(__file__).resolve().parent
    try:
        if action == "register":
            register(root)
            print(".fbs files are now associated with FieldBook Sync for this Windows user.")
        elif action == "unregister":
            unregister()
            print("FieldBook Sync .fbs file association was removed for this Windows user.")
        else:
            print("Usage: file_association.py [register|unregister]")
            return 2
    except Exception as exc:
        print(f"File association failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
