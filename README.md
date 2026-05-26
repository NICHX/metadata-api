# Metadata API

**版本**: 1.1.2 | **语言**: Python | **框架**: FastAPI

媒体归档刮削助手 API，用于自动识别、刮削和整理媒体文件（电影/剧集）。支持从文件名解析媒体信息，通过 TMDb、Bangumi 等数据源获取元数据，并生成 Kodi 兼容的 NFO 文件和海报图片。

---

## 功能特性

- **文件名解析** — 使用 `guessit` 智能解析文件名中的标题、季、集等信息
- **媒体识别** — 通过 TMDb / Bangumi 数据源匹配并识别媒体内容
- **AI 辅助识别** — 集成 OpenAI 兼容 API（如 DeepSeek），从目录路径推断剧名/电影名
- **元数据刮削** — 写入 Kodi 标准 NFO 文件（剧集、季、剧集目录）
- **图片下载** — 自动下载海报、剧照、背景图等
- **文件系统管理** — 浏览本地目录、递归扫描媒体文件
- **硬链接整理** — 按 `{剧名 (年份)/Season NN/剧名 - SNNENN.ext` 格式硬链接/复制到目标媒体库
- **批量处理** — 批量识别 + 批量刮削，支持流式实时返回结果
- **Web UI** — 内置浏览器界面，CSS/JS 外部分离，开箱即用
- **双模式部署** — 本地模式（完整文件操作）/ 远程模式（仅 API）
- **双认证机制** — Header 认证（API 请求） + Session 认证（Web UI 登录）
- **TMDb 防护** — 未配置 TMDb API Key 时自动禁用硬链接/刮削功能
- **智能缓存** — 多层级缓存（API 结果、AI 结果），减少重复请求
- **API 限流** — 针对 TMDb / BGM 接口内置令牌桶限流器

---

## 快速开始

### 环境要求

- Python 3.10+
- TMDb API 密钥（[申请地址](https://www.themoviedb.org/settings/api)）
- （可选）Bangumi API 密钥、OpenAI 兼容 API 密钥

### 安装

```bash
pip install -r requirements.txt
```

### 启动

```bash
python main_api.py
```

默认监听 `0.0.0.0:8000`，启动后可通过以下地址访问：

| 地址 | 说明 |
|------|------|
| `http://localhost:8000` | 自动跳转 Web UI（本地模式） |
| `http://localhost:8000/web-ui` | Web 管理界面 |
| `http://localhost:8000/docs` | Swagger API 文档 |
| `http://localhost:8000/redoc` | ReDoc API 文档 |
| `http://localhost:8000/health` | 健康检查 |

### 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | `0.0.0.0` | 监听地址 |
| `--port` | `8000` | 监听端口 |
| `--mode` | `local` | 部署模式：`local` / `remote` |
| `--auth` | （空） | API 认证密钥，留空则不启用鉴权 |
| `--local-only` | — | 仅允许本地访问 (127.0.0.1) |
| `--reload` | — | 开发模式自动重载 |

---

## Docker 部署

### 方式一：GitHub Actions 自动构建

推送 `v*` 格式的 Git 标签时，GitHub Actions 会自动构建镜像并推送到 GitHub Container Registry：

```bash
# 推送标签触发构建
git tag v1.0.0
git push origin v1.0.0

# 拉取最新镜像
docker pull ghcr.io/你的GitHub用户名/metadata-api:latest

# 运行
docker run -d \
  -p 8000:8000 \
  -e METADATA_MODE=local \
  -e METADATA_AUTH_KEY=your_secret_key \
  -e METADATA_TMDB_API_KEY=your_key \
  -e MEDIA_LIBRARY=/media/library \
  -v /path/to/media:/media:ro \
  -v metadata-api-data:/app/data \
  ghcr.io/你的GitHub用户名/metadata-api:latest
```

> 首次使用前需在 GitHub 仓库 Settings → Actions → General 中确保 **Workflow permissions** 设为 **Read and write permissions**。

### 方式二：本地构建

```bash
docker build -t metadata-api .
docker run -d \
  -p 8000:8000 \
  -e METADATA_MODE=local \
  -e METADATA_AUTH_KEY=your_secret_key \
  -e METADATA_TMDB_API_KEY=your_key \
  -e MEDIA_LIBRARY=/media/library \
  -v /path/to/media:/media:ro \
  -v metadata-api-data:/app/data \
  metadata-api
```

### 方式三：Docker Compose

```bash
docker compose up -d
```

Docker Compose 会自动创建 `media-renamer-data` 卷，将配置文件和 API 缓存持久化到宿主机。

### 环境变量

所有配置项均可通过环境变量设置，环境变量前缀为 `METADATA_`：

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `METADATA_MODE` | `local` | 部署模式：`local`（完整文件操作）/ `remote`（仅 API） |
| `METADATA_HOST` | `0.0.0.0` | 监听地址 |
| `METADATA_PORT` | `8000` | 监听端口 |
| `METADATA_AUTH_KEY` | （空） | API 认证密钥，请求需在 `Authorization` 或 `Authentication` 头中携带此值，留空则不启用鉴权 |
| `METADATA_WEB_USERNAME` | （空） | Web UI 基础认证用户名，与 `METADATA_WEB_PASSWORD` 同时设置后生效 |
| `METADATA_WEB_PASSWORD` | （空） | Web UI 基础认证密码，与 `METADATA_WEB_USERNAME` 同时设置后生效 |
| `METADATA_TMDB_API_KEY` | （空） | TMDb API 密钥 |
| `METADATA_BGM_API_KEY` | （空） | Bangumi API 密钥 |
| `METADATA_AI_API_KEY` | （空） | AI API 密钥（OpenAI 兼容） |
| `METADATA_AI_BASE_URL` | `https://api.deepseek.com` | AI API 地址 |
| `METADATA_AI_MODEL` | `deepseek-v4-flash` | AI 模型名称 |
| `METADATA_AI_MAX_TOKENS` | `10000` | AI 最大 Token 数 |
| `MEDIA_LIBRARY` | `/media/library` | 媒体库目标目录（整理/刮削的默认路径） |

> 环境变量优先级高于 JSON 配置文件中的对应字段。若已设置环境变量，配置文件中的同名字段将被忽略。

---

## API 概览

所有 API 端点均在 Swagger 文档（`/docs`）中完整列出。

### 认证接口 (`/api/v1/auth`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/login` | Web UI 登录 |
| POST | `/logout` | 登出 |
| GET | `/check` | 检查登录状态 |

### 识别接口 (`/api/v1/recognition`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/parse` | 解析文件名（本地解析，无需网络） |
| POST | `/recognize` | 识别单个媒体（查询 TMDb / BGM） |
| POST | `/batch-recognize` | 批量识别 |
| POST | `/batch-recognize/stream` | 批量识别（流式返回） |

### 媒体操作接口 (`/api/v1/media`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/preview-rename` | 预览重命名 |
| POST | `/tmdb-search` | TMDb 搜索（手动刮削选配） |
| POST | `/manual-scrape` | 手动刮削（返回列表） |
| POST | `/manual-scrape/stream` | 手动刮削（流式） |
| POST | `/scrape` | 自动刮削元数据（NFO + 图片） |
| POST | `/scrape/stream` | 流式刮削 |
| POST | `/rename` | 重命名文件 |
| POST | `/organize` | 归档整理（硬链接/复制/移动） |
| GET | `/image` | 代理获取 TMDb 图片 |
| GET | `/image-url` | 获取 TMDb 图片外链 |

### 文件系统接口 (`/api/v1/filesystem`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/browse` | 浏览目录内容 |
| POST | `/scan` | 扫描目录中的媒体文件 |
| POST | `/scan/stream` | 流式扫描（NDJSON 实时推送） |

### 配置接口 (`/api/v1/config`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `` | 获取当前配置 |
| PUT | `` | 更新配置 |
| POST | `/clear-cache` | 清除 API 缓存 |

---

## 项目结构

```
metadata-api/
├── .github/workflows/       # GitHub Actions CI 配置
│   └── docker-build.yml     # Docker 镜像自动构建
├── api/                     # FastAPI 应用
│   ├── main.py              # 应用入口，路由注册
│   ├── config.py            # 配置管理（环境变量、JSON 文件）
│   ├── dependencies.py      # FastAPI 依赖（认证、模式校验）
│   ├── routes/              # API 路由
│   │   ├── auth.py          # 登录/登出
│   │   ├── recognition.py   # 媒体识别接口
│   │   ├── media_operations.py  # 刮削/重命名/图片接口
│   │   ├── config.py        # 配置管理接口
│   │   ├── filesystem.py    # 文件系统浏览/扫描接口
│   │   └── web_ui.py        # Web UI 路由
│   ├── schemas/             # Pydantic 数据模型
│   │   ├── common.py        # 通用模型（EpisodeMetadata）
│   │   └── media.py         # 媒体相关模型
│   ├── services/            # 业务逻辑
│   │   ├── recognition_service.py   # 媒体识别服务
│   │   ├── media_operations_service.py  # 刮削服务（NFO/图片）
│   │   ├── hardlink_service.py     # 硬链接/复制/移动整理
│   │   └── ai_service.py    # AI 推断服务（OpenAI 兼容）
│   ├── static/              # 静态资源（CSS/JS 外部分离）
│   │   ├── css/web_ui.css   # Web UI 样式
│   │   └── js/web_ui.js     # Web UI 交互逻辑
│   └── templates/           # Jinja2 模板
│       └── web_ui.html      # Web UI 页面
├── data/                    # 运行时数据卷（自动创建）
│   ├── metadata_api_config.json  # 持久化配置文件
│   └── api_cache.json       # API 缓存（TMDb/BGM）
├── db/                      # 数据源集成
│   └── tmdb_api.py          # TMDb / Bangumi API 封装
├── utils/                   # 工具函数
│   └── helpers.py           # 缓存、NFO 写入、图片下载等
├── main_api.py              # CLI 启动入口
├── api_client.py            # Python 客户端调用示例
├── requirements.txt         # Python 依赖
├── Dockerfile               # Docker 构建文件
├── docker-compose.yml       # Docker Compose 配置
└── docker-entrypoint.sh     # Docker 启动脚本
```

---

## 技术栈

- **[FastAPI](https://fastapi.tiangolo.com/)** — 高性能 Web 框架
- **[uvicorn](https://www.uvicorn.org/)** — ASGI 服务器
- **[Pydantic](https://docs.pydantic.dev/)** — 数据验证与序列化
- **[guessit](https://guessit.readthedocs.io/)** — 文件名智能解析
- **[OpenAI Python SDK](https://github.com/openai/openai-python)** — AI API 调用
- **[Jinja2](https://jinja.palletsprojects.com/)** — 模板引擎
- **[requests](https://requests.readthedocs.io/)** — HTTP 客户端

---

## 数据源

| 数据源 | 用途 | 是否需要 API Key |
|--------|------|-----------------|
| [TMDb](https://www.themoviedb.org/) | 电影/剧集元数据、图片 | 是 |
| [Bangumi](https://bgm.tv/) | 番组/动画元数据 | 可选 |
| OpenAI 兼容 API | AI 辅助标题推断（默认 DeepSeek） | 可选 |

---

## 整理命名规则

| 类型 | 默认格式 |
|------|----------|
| **电影** | `{标题} ({年份})/{标题}.{扩展名}` |
| **电视剧** | `{标题} ({年份})/Season {季号:02d}/{标题} - S{季号:02d}E{集号:02d} - {集名}.{扩展名}` |

实际效果：
```
/媒体库/电影/黑豹 (2018)/黑豹 (2018) 2160p Atmos.mkv
/媒体库/电视剧/田耕纪 (2023)/Season 01/田耕纪 - S01E25 - .mp4
```

---

## 更新日志

### v1.1.2 (2026-05-26)

- **改进**: Web UI CSS/JS 外部分离，单 HTML 从 2575 行降至 449 行
- **修复**: 扫描/刮削接口 403 Forbidden（JavaScript fetch 缺少 Authorization header）
- **修复**: Docker 重启后非敏感配置丢失（entrypoint 接管所有 METADATA_* 环境变量写入）
- **修复**: 关于页面无法加载（异步竞态问题）
- **新增**: 电视剧整理文件夹名自动追加年份 `田耕纪 (2023)`
- **新增**: 未配置 TMDb API Key 时自动禁用硬链接/刮削 tab
- **安全**: auth_key、ai_api_key、web_username/password 仅从环境变量注入，不入配置文件

---

## 开发

```bash
# 开发模式启动（自动重载）
python main_api.py --reload

# 仅本地访问
python main_api.py --local-only

# 远程模式（仅 API，无文件操作）
python main_api.py --mode remote
```

---

## 许可证

本项目基于 MIT 许可证开源。