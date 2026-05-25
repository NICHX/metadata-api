#!/bin/sh
set -e

# 创建数据目录（卷挂载点）
mkdir -p /app/data

# 将环境变量写入配置文件，确保配置持久化
python3 -c "
import json, os

DATA_DIR = 'data'
config = {}
config_path = os.path.join(DATA_DIR, 'metadata_api_config.json')

# 读取已有配置
if os.path.exists(config_path):
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except Exception:
        config = {}

# 环境变量覆盖（METADATA_ 前缀的变量由 pydantic-settings 自动读取）
# 这里手动写入文件，确保配置持久化
tmdb_key = os.environ.get('METADATA_TMDB_API_KEY', '')
bgm_key = os.environ.get('METADATA_BGM_API_KEY', '')
mode = os.environ.get('METADATA_MODE', '')
web_user = os.environ.get('METADATA_WEB_USERNAME', '')
web_pass = os.environ.get('METADATA_WEB_PASSWORD', '')

if tmdb_key:
    config['tmdb_api_key'] = tmdb_key
if bgm_key:
    config['bgm_api_key'] = bgm_key

# 部署模式由 pydantic-settings 在运行时自动读取 METADATA_MODE 环境变量，
# 无需写入配置文件，但在此记录以便运维确认
if mode:
    print(f'  METADATA_MODE={mode}')

# 写回配置文件
os.makedirs(DATA_DIR, exist_ok=True)
with open(config_path, 'w') as f:
    json.dump(config, f, ensure_ascii=False, indent=2)

print(f'配置已持久化 -> {config_path}')
if tmdb_key:
    print('  METADATA_TMDB_API_KEY ✓')
if bgm_key:
    print('  METADATA_BGM_API_KEY ✓')
if web_user and web_pass:
    print('  METADATA_WEB_USERNAME/METADATA_WEB_PASSWORD ✓')

# 检查 API 缓存卷状态
cache_path = os.path.join(DATA_DIR, 'api_cache.json')
if os.path.exists(cache_path):
    try:
        size = os.path.getsize(cache_path)
        print(f'缓存已就绪 -> {cache_path} ({size / 1024:.1f} KB)')
    except Exception:
        print(f'缓存文件存在 -> {cache_path}')
else:
    print(f'缓存文件不存在 -> {cache_path}（首次启动，运行后将自动创建）')
"

# 启动主应用
exec "$@"