# KAIRO — 编码规范

## Electron
- main process 只做系统交互，业务逻辑在 renderer
- IPC 通信用 contextBridge，不暴露 Node API
- preload.js 最小化暴露面

## 模型集成
- 绝不硬编码 API key
- 模型调用统一抽象层，方便切换 Seedance/Qwen3-VL/InternVL
- 每个 pipeline step 有超时和重试机制

## 视频处理
- ffmpeg 调用封装为独立模块
- 临时文件用完即删
- 输出格式标准化：9:16 竖屏, 1080x1920
