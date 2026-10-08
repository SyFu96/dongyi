"""当前用户的静默启动快捷方式；无需管理员权限。"""

from pathlib import Path
import os

from win32com.client import Dispatch
from win32com.shell import shell, shellcon

APP_DIR = Path(__file__).resolve().parent


def startup_shortcut() -> Path:
    return Path(shell.SHGetFolderPath(0, shellcon.CSIDL_STARTUP, None, 0)) / "划译.lnk"


def is_enabled() -> bool:
    link = startup_shortcut()
    if not link.exists():
        return False
    shortcut = Dispatch("WScript.Shell").CreateShortcut(str(link))
    return str(APP_DIR / "launch.vbs").casefold() in shortcut.Arguments.casefold()


def create_shortcut(path: Path) -> None:
    shortcut = Dispatch("WScript.Shell").CreateShortcut(str(path))
    shortcut.TargetPath = str(Path(os.environ["WINDIR"]) / "System32" / "wscript.exe")
    shortcut.Arguments = '//B //Nologo "' + str(APP_DIR / "launch.vbs") + '"'
    shortcut.WorkingDirectory = str(APP_DIR)
    shortcut.WindowStyle = 7
    shortcut.IconLocation = str(APP_DIR / "assets" / "huayi.ico")
    shortcut.Description = "划译 — 后台划词翻译与追问"
    shortcut.Save()


def set_enabled(enabled: bool) -> None:
    path = startup_shortcut()
    if enabled:
        create_shortcut(path)
    elif is_enabled():
        path.unlink()  # 仅移除本项目在当前用户启动目录的快捷方式。


def install() -> None:
    desktop = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOPDIRECTORY, None, 0))
    create_shortcut(desktop / "划译.lnk")
    set_enabled(True)
    print("已更新桌面启动入口，并启用当前用户登录时自动启动。")


if __name__ == "__main__":
    install()
