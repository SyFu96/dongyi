# -*- coding: utf-8 -*-
"""网络小工具：不跟随重定向地打开 URL。

用于本机探测/模型列表等场景——避免服务端用 3xx 把请求重定向到非预期主机。
"""

from __future__ import annotations

import urllib.request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        return None  # 不跟随；调用方按 HTTPError 处理


_opener = urllib.request.build_opener(_NoRedirect)


def open_no_redirect(url_or_request, timeout: float = 5.0):
    """打开 URL，但不跟随重定向（遇到 3xx 会抛 urllib.error.HTTPError）。"""
    return _opener.open(url_or_request, timeout=timeout)
