# KAIRO — 技术架构

## 概述
游戏直播 VOD → 自动化短视频生成 Pipeline。
核心：主播高赞视频 → 模板 → 人设画像 → VOD 匹配 → 个性化剪辑。

## 技术栈
- **桌面**: Electron (main.js + preload.js + renderer/)
- **核心逻辑**: `src/` 目录
- **模型约束**: ⚠️ 不能用 Google/Anthropic/OpenAI（字节竞争对手限制）→ 走内部模型 (Seedance) + 开源 (Qwen3-VL/InternVL)

## Pipeline
```
主播高赞视频 → 模板提取
         ↓
    人设画像生成
         ↓
VOD 回放 → 匹配模板 → 个性化剪辑 → 短视频输出
```

## 差异化
- 个性化模板 + 人设匹配（不是通用 auto-clip）
- Gaming 垂直场景
- Agent 方式，类似 Claude Code 的工作流
- 卖工作流不是卖工具

## 约束
- 多模态模型只能用内部/开源
- 资源分配影响 agent 表现（Anthropic 研究：同一 agent 不同配置差 6%）
- 目标用户：中腰部游戏主播
