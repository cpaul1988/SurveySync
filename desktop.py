from __future__ import annotations

import os
import socket
import sys
import threading
import time
from contextlib import closing
from pathlib import Path

import uvicorn
import webview

from fieldbook_sync import app as field_app
from fieldbook_sync.app import load_project_path_into_runtime
from file_association import register as register_fbs, unregister as unregister_fbs

APP_NAME = "SurveySync v9.3.2"


class NativeBridge:
    def __init__(self) -> None:
        self._window = None
        self._shutdown_callback = None

    def exit_app(self) -> bool:
        try:
            if self._shutdown_callback: self._shutdown_callback()
            elif self._window: self._window.destroy()
            return True
        except Exception:
            return False

    def _dialog_type(self, name: str):
        fd=getattr(webview,"FileDialog",None)
        return getattr(fd,name) if fd is not None else getattr(webview,f"{name}_DIALOG")

    def choose_folder(self, initial_directory: str="") -> str | None:
        if not self._window:return None
        result=self._window.create_file_dialog(self._dialog_type("FOLDER"),directory=initial_directory or "")
        return str(result[0]) if result else None

    def choose_file(self, initial_directory: str="", file_types: tuple[str,...]|None=None) -> str | None:
        if not self._window:return None
        result=self._window.create_file_dialog(self._dialog_type("OPEN"),directory=initial_directory or "",allow_multiple=False,file_types=file_types or ("All files (*.*)",))
        return str(result[0]) if result else None

    def choose_files(self, initial_directory: str="", file_types: tuple[str,...]|None=None) -> list[str]:
        if not self._window:return []
        result=self._window.create_file_dialog(self._dialog_type("OPEN"),directory=initial_directory or "",allow_multiple=True,file_types=file_types or ("All files (*.*)",))
        return [str(x) for x in (result or [])]

    def choose_save_file(self, suggested_name: str="SurveySync_Project.fbs", initial_directory: str="", file_types: tuple[str,...]|None=None) -> str | None:
        if not self._window:return None
        try:
            result=self._window.create_file_dialog(
                self._dialog_type("SAVE"),
                directory=initial_directory or "",
                save_filename=suggested_name or "SurveySync_Project.fbs",
                file_types=file_types or ("FieldBook Sync Project (*.fbs)", "All files (*.*)"),
            )
        except TypeError:
            result=self._window.create_file_dialog(self._dialog_type("SAVE"),directory=initial_directory or "",file_types=file_types or ("FieldBook Sync Project (*.fbs)", "All files (*.*)"))
        return str(result[0]) if result else None

    def choose_arcgis_project(self, initial_directory: str="") -> str | None:
        return self.choose_file(initial_directory,("ArcGIS Projects (*.aprx;*.mxd)","ArcGIS Pro Project (*.aprx)","ArcMap Document (*.mxd)"))

    def choose_aprx(self, initial_directory: str="") -> str | None:
        return self.choose_arcgis_project(initial_directory)

    def reveal_folder(self, path: str) -> bool:
        try:
            p=Path(path).expanduser().resolve()
            if sys.platform=="win32":os.startfile(str(p))
            return True
        except Exception:return False


def _wait(host: str,port: int,timeout: float=12.0)->bool:
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        with closing(socket.socket(socket.AF_INET,socket.SOCK_STREAM)) as sock:
            sock.settimeout(.25)
            try:sock.connect((host,port));return True
            except OSError:time.sleep(.08)
    return False


def main()->None:
    from surveysync.router import config_store as ss_config_store
    from surveysync.session_recovery import begin_session, end_session, set_project
    args_raw=[a for a in sys.argv[1:] if a.strip()]
    root=Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parent
    if "--register-fbs" in args_raw:
        register_fbs(root); return
    if "--unregister-fbs" in args_raw:
        unregister_fbs(); return
    begin_session(ss_config_store.root)
    host="127.0.0.1";port=field_app._choose_port(host,8765)
    # Optional command-line open of an existing SurveySync project folder.
    args=[a.strip('"') for a in args_raw if a and not a.startswith('--')]
    if not args:
        from surveysync.router import restore_last_project
        restore_last_project()
    if args:
        p=Path(args[0]).expanduser()
        if p.is_dir() and (p/"survey_sync_project.json").exists():
            from surveysync.project import SurveyProject
            from surveysync.router import _set_current
            _set_current(SurveyProject(p))
            set_project(ss_config_store.root, p)
        elif p.is_file() and p.suffix.lower()==".fbs":
            # Backward-compatible direct open; users can migrate this legacy state into a chosen v9 project from Project.
            load_project_path_into_runtime(p)
    config=uvicorn.Config(field_app.app,host=host,port=port,log_level="warning",access_log=False)
    server=uvicorn.Server(config);server.install_signal_handlers=lambda:None
    thread=threading.Thread(target=server.run,name="SurveySyncServer",daemon=True);thread.start()
    if not _wait(host,port):server.should_exit=True;raise RuntimeError("SurveySync could not start its local application service.")
    bridge=NativeBridge();window=webview.create_window(APP_NAME,f"http://{host}:{port}",width=1500,height=940,min_size=(1050,680),background_color="#0f172a",text_select=True)
    bridge._window=window
    window.expose(bridge.exit_app,bridge.choose_folder,bridge.choose_file,bridge.choose_files,bridge.choose_save_file,bridge.choose_arcgis_project,bridge.choose_aprx,bridge.reveal_folder)
    shutdown_lock=threading.Lock();shutdown_started=False
    def shutdown(close_window=True):
        nonlocal shutdown_started
        with shutdown_lock:
            if shutdown_started:return
            shutdown_started=True
        field_app.request_application_shutdown("SurveySync window closed.");server.should_exit=True
        end_session(ss_config_store.root)
        if close_window:
            try:window.destroy()
            except Exception:pass
    bridge._shutdown_callback=shutdown
    window.events.closed += lambda: shutdown(False)
    webview.start(gui="edgechromium" if sys.platform=="win32" else None,debug=False)
    shutdown(False);thread.join(timeout=8);field_app.finalize_application_shutdown()

if __name__=="__main__":main()
