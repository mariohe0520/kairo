# KAIRO macOS App - Engineering Architecture

## 项目定位
本地优先的 AI 视频剪辑工具，结合本地模型能力 + 云端视频生成 API

## 技术栈

### 前端 (macOS App)
- **语言**: Swift 5.9+
- **UI框架**: SwiftUI + AppKit (混合)
- **最低版本**: macOS 14.0 (Sonoma)
- **架构**: MVVM + Clean Architecture

### 本地模型层 (已部署)
| 模型 | 用途 | 路径 |
|------|------|------|
| mflux | 图像生成 | `~/.openclaw/models/mflux-env/` |
| Kokoro | TTS语音 | `~/.openclaw/models/kokoro-env/` |
| Whisper | 语音转文字 | `~/.openclaw/models/whisper-env/` |
| Qwen3-VL | 视频理解 | `~/.openclaw/models/qwen3vl-env/` |

### 云端 API 层 (待接入)
| 服务 | 用途 | 接入方式 |
|------|------|----------|
| Seedance 2.0 | 视频生成 | REST API + API Key |

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    KAIRO App (SwiftUI)                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ 视频输入模块 │  │ 剪辑工作台   │  │ 导出/分享模块       │  │
│  │ - 本地上传   │  │ - 时间轴     │  │ - MP4导出          │  │
│  │ - YouTube   │  │ - AI特效     │  │ - 直接上传         │  │
│  │ - 链接解析   │  │ - 字幕生成   │  │ - 模板保存         │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
│         │                │                     │             │
│         └────────────────┼─────────────────────┘             │
│                          │                                   │
│  ┌───────────────────────▼───────────────────────────────┐  │
│  │                 Pipeline Orchestrator                  │  │
│  │              (本地处理 → API调用 → 合成)                │  │
│  └───────────────────────┬───────────────────────────────┘  │
│                          │                                   │
└──────────────────────────┼───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                    Processing Layer                           │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐  │
│  │  Local Models   │  │  External APIs  │  │   Fallback   │  │
│  │                 │  │                 │  │              │  │
│  │  ┌───────────┐  │  │  ┌───────────┐  │  │  ┌────────┐  │  │
│  │  │ mflux     │  │  │  │ Seedance  │  │  │  │其他API │  │  │
│  │  │ (图像)    │──┼──┼──│ 2.0       │  │  │  │(备用)  │  │  │
│  │  └───────────┘  │  │  │ (视频)    │  │  │  └────────┘  │  │
│  │                 │  │  └───────────┘  │  │              │  │
│  │  ┌───────────┐  │  │                 │  │              │  │
│  │  │ Kokoro    │  │  │  ┌───────────┐  │  │              │  │
│  │  │ (TTS)     │──┘  │  │ Google    │  │  │              │  │
│  │  └───────────┘     │  │ Gemini    │──┼──┘              │  │
│  │                    │  │ (备用)    │  │                 │  │
│  │  ┌───────────┐     │  └───────────┘  │                 │  │
│  │  │ Whisper   │     │                 │                 │  │
│  │  │ (STT)     │─────┘                 │                 │  │
│  │  └───────────┘                       │                 │  │
│  │                                      │                 │  │
│  │  ┌───────────┐                       │                 │  │
│  │  │ Qwen3-VL  │                       │                 │  │
│  │  │ (视频理解)│                       │                 │  │
│  │  └───────────┘                       │                 │  │
│  └─────────────────┘  └─────────────────┘  └──────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

---

## 核心模块设计

### 1. Video Input Module
```swift
protocol VideoInputProtocol {
    func uploadLocalVideo(url: URL) async throws -> VideoAsset
    func downloadYouTubeVideo(url: String) async throws -> VideoAsset
    func analyzeVideoContent(asset: VideoAsset) async throws -> VideoAnalysis
}

struct VideoAsset {
    let id: UUID
    let localURL: URL
    let duration: TimeInterval
    let resolution: CGSize
    let fps: Double
}

struct VideoAnalysis {
    let scenes: [Scene]           // Qwen3-VL 分析
    let transcript: String?       // Whisper 转录
    let highlights: [TimeRange]   // AI识别高光时刻
}
```

### 2. AI Processing Pipeline
```swift
enum AITask {
    case generateImage(prompt: String)           // mflux
    case generateVideo(prompt: String, refImage: URL?)  // Seedance 2.0
    case generateAudio(text: String, voice: Voice)      // Kokoro
    case transcribeAudio(audioURL: URL)         // Whisper
    case analyzeVideo(videoURL: URL)            // Qwen3-VL
}

protocol AITaskExecutor {
    func execute(_ task: AITask) async throws -> AIResult
}

// 本地模型执行器
class LocalModelExecutor: AITaskExecutor {
    private let mfluxPath = "~/.openclaw/models/mflux-env/bin/mflux-generate"
    private let kokoroPath = "~/.openclaw/models/kokoro-env/bin/kokoro"
    
    func execute(_ task: AITask) async throws -> AIResult {
        // 调用本地 Python 脚本
    }
}

// Seedance API 执行器
class SeedanceAPIExecutor: AITaskExecutor {
    private let baseURL = "https://seedanceapi.org/v1"
    private var apiKey: String
    
    func execute(_ task: AITask) async throws -> AIResult {
        // 调用 Seedance 2.0 API
    }
}
```

### 3. Template System
```swift
struct Template {
    let id: String
    let name: String
    let description: String
    let category: TemplateCategory
    let parameters: [TemplateParameter]
    let renderPipeline: RenderPipeline
}

enum TemplateCategory {
    case gaming        // 游戏高光
    case vlog         // 日常vlog
    case tutorial     // 教程
    case cinematic    // 电影感
}

// 模板参数
struct TemplateParameter {
    let key: String
    let type: ParameterType
    let defaultValue: Any
    let description: String
}

// 渲染管道
struct RenderPipeline {
    let steps: [RenderStep]
}

enum RenderStep {
    case extractHighlights          // 提取高光
    case generateTransition         // 生成转场
    case addSubtitle(text: String)  // 添加字幕
    case addBGM(music: URL)         // 添加BGM
    case applyFilter(filter: Filter) // 滤镜
    case generateBroll(prompt: String) // AI生成B-roll
}
```

---

## Seedance 2.0 集成方案

### API Client
```swift
class SeedanceAPIClient {
    private let baseURL = "https://seedanceapi.org/v1"
    private let apiKey: String
    
    // 生成视频
    func generateVideo(
        prompt: String,
        aspectRatio: AspectRatio = .r16_9,
        resolution: Resolution = .p720,
        duration: Duration = .s8,
        generateAudio: Bool = true,
        referenceImage: URL? = nil
    ) async throws -> GenerationTask {
        
        var requestBody: [String: Any] = [
            "prompt": prompt,
            "aspect_ratio": aspectRatio.rawValue,
            "resolution": resolution.rawValue,
            "duration": duration.rawValue,
            "generate_audio": generateAudio
        ]
        
        if let imageURL = referenceImage {
            requestBody["image_urls"] = [imageURL.absoluteString]
        }
        
        // POST /v1/generate
        let task = try await post("/generate", body: requestBody)
        return task
    }
    
    // 查询状态
    func checkStatus(taskId: String) async throws -> TaskStatus {
        // GET /v1/status?task_id=xxx
        let status = try await get("/status?task_id=\(taskId)")
        return status
    }
}

// 使用示例
let client = SeedanceAPIClient(apiKey: "YOUR_API_KEY")
let task = try await client.generateVideo(
    prompt: "Epic gaming highlight, cinematic slow motion, dramatic lighting",
    aspectRatio: .r16_9,
    resolution: .p720,
    duration: .s8,
    generateAudio: true,
    referenceImage: highlightFrameURL
)

// 轮询检查状态
while true {
    let status = try await client.checkStatus(taskId: task.id)
    if status.state == .completed {
        let videoURL = status.response[0]
        // 下载视频
        break
    }
    try await Task.sleep(nanoseconds: 5_000_000_000) // 5秒
}
```

---

## 本地模型调用封装

### Python Bridge (已存在)
```python
# local_models.py - 本地模型统一接口
import subprocess
import json

def generate_image(prompt: str, output_path: str):
    """调用 mflux 生成图像"""
    cmd = [
        "mflux-generate",
        "--model", "schnell",
        "--prompt", prompt,
        "--output", output_path,
        "--steps", "4",
        "--width", "512",
        "--height", "512"
    ]
    subprocess.run(cmd, check=True)
    return output_path

def text_to_speech(text: str, output_path: str, voice: str = "af"):
    """调用 Kokoro TTS"""
    cmd = [
        "python3", "-m", "kokoro",
        "--text", text,
        "--output", output_path,
        "--voice", voice
    ]
    subprocess.run(cmd, check=True)
    return output_path

def transcribe_audio(audio_path: str) -> str:
    """调用 Whisper 转录"""
    import whisper
    model = whisper.load_model("base")
    result = model.transcribe(audio_path)
    return result["text"]
```

### Swift 调用封装
```swift
class LocalModelBridge {
    private let pythonPath = "/Users/mario/.openclaw/models/kokoro-env/bin/python3"
    
    func generateImage(prompt: String) async throws -> URL {
        let outputPath = tempDirectory.appendingPathComponent("\(UUID().uuidString).png")
        
        let process = Process()
        process.executableURL = URL(fileURLWithPath: pythonPath)
        process.arguments = [
            "-c",
            """
            import sys
            sys.path.insert(0, '/Users/mario/.openclaw/workspace/scripts')
            from local_models import generate_image
            generate_image("\(prompt)", "\(outputPath.path)")
            """
        ]
        
        try await process.runAsync()
        return outputPath
    }
}
```

---

## 项目文件结构

```
KAIRO/
├── KAIRO.xcodeproj
├── KAIRO/
│   ├── App/
│   │   ├── KAIROApp.swift
│   │   └── AppDelegate.swift
│   ├── Core/
│   │   ├── Models/
│   │   ├── Services/
│   │   └── Utils/
│   ├── Features/
│   │   ├── Input/
│   │   ├── Editor/
│   │   ├── Export/
│   │   └── Settings/
│   ├── AI/
│   │   ├── LocalModelBridge.swift
│   │   ├── SeedanceAPIClient.swift
│   │   └── PipelineOrchestrator.swift
│   └── Resources/
│       ├── Assets.xcassets
│       └── Templates/
├── PythonBridge/
│   ├── local_models.py
│   └── api_client.py
└── docs/
    ├── ARCHITECTURE.md
    └── API_INTEGRATION.md
```

---

## 开发路线图

### Phase 1: Foundation (Week 1-2)
- [ ] Xcode 项目初始化
- [ ] SwiftUI 基础界面
- [ ] 本地视频导入
- [ ] Python Bridge 搭建

### Phase 2: Local AI (Week 3-4)
- [ ] mflux 图像生成集成
- [ ] Kokoro TTS 集成
- [ ] Whisper 语音转录
- [ ] Qwen3-VL 视频分析

### Phase 3: Cloud API (Week 5-6)
- [ ] Seedance 2.0 API 接入
- [ ] 视频生成 Pipeline
- [ ] 任务队列管理
- [ ] 错误处理 & 重试

### Phase 4: Polish (Week 7-8)
- [ ] 模板系统
- [ ] 导出功能
- [ ] 设置面板
- [ ] 性能优化

---

## API Key 管理

```swift
class APIKeyManager {
    static let shared = APIKeyManager()
    
    // 使用 Keychain 存储
    func saveSeedanceAPIKey(_ key: String) {
        Keychain.save(key, service: "com.mario.kairo.seedance")
    }
    
    func getSeedanceAPIKey() -> String? {
        return Keychain.load(service: "com.mario.kairo.seedance")
    }
}
```

---

*Design Complete - Ready for Implementation*
