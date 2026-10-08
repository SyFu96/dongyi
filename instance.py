"""同一项目只运行一个实例；再次启动时通知后台实例。"""

from __future__ import annotations

import hashlib
import ctypes
from ctypes import wintypes
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    activated = Signal()

    def __init__(self, project_dir: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        identity = str(project_dir.resolve()).casefold().encode("utf-8")
        self.name = "huayi-" + hashlib.sha256(identity).hexdigest()[:24]
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._accept)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self._kernel32.CreateMutexW.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._mutex = None

    def acquire(self) -> bool:
        # Windows 的命名管道允许多个 server 使用同名，需用互斥量保证唯一实例。
        handle = self._kernel32.CreateMutexW(None, False, "Local\\" + self.name)
        error = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(error)
        if error != 183:  # ERROR_ALREADY_EXISTS
            self._mutex = handle
            if not self.server.listen(self.name):
                self.close()
                raise RuntimeError("无法建立划译实例服务：" + self.server.errorString())
            return True
        self._kernel32.CloseHandle(handle)
        client = QLocalSocket()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            client.abort()
            client.connectToServer(self.name)
            if client.waitForConnected(100):
                break
            # 首个实例可能刚取得互斥量，还没来得及监听管道。
            time.sleep(0.02)
        else:
            raise RuntimeError("无法建立划译实例连接：" + self.server.errorString())
        client.write(b"show\n")
        client.flush()
        if client.bytesToWrite():
            client.waitForBytesWritten(1500)
        client.disconnectFromServer()
        return False

    def _accept(self) -> None:
        while self.server.hasPendingConnections():
            connection = self.server.nextPendingConnection()
            # 连接成功就表示用户再次启动；不依赖请求字节到达的先后顺序。
            self.activated.emit()
            connection.disconnected.connect(connection.deleteLater)
            if connection.state() == QLocalSocket.UnconnectedState:
                connection.deleteLater()

    def close(self) -> None:
        self.server.close()
        if self._mutex is not None:
            self._kernel32.CloseHandle(self._mutex)
            self._mutex = None
