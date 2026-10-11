划译 v0.1.0 — Windows x64
========================

怎么用
------
1. 把整个 huayi 文件夹解压到任意位置（不要只拿走 huayi.exe，_internal 目录必须一起）。
2. 双击 huayi.exe。
3. 在任意应用里选中文字，点击选区旁的「译」图标；或托盘右键 →「设置…」。

模型配置
--------
- 本地翻译：需自行安装 Ollama 并下载模型（例如 qwen3-vl:30b-a3b-instruct）。
- 云端翻译：在「设置…」里选择「云端 API」，填写 OpenAI 兼容的地址 / 模型 / API Key。
- 想保证不外发：在「设置…」里勾选「严格离线」。

数据位置
--------
- 配置与日志：%APPDATA%\huayi\
- 退出程序：托盘右键 → 退出。

许可与源码
----------
本程序采用 GPL-3.0-only。完整许可与第三方声明见：
  LICENSE、THIRD_PARTY_NOTICES.md、LICENSES/、SOURCE_CODE.md、BUILDING.md

本版本为首次公开测试版（Alpha）。
