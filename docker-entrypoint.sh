#!/bin/sh
set -e

# 将环境变量写入配置文件，确保配置持久化
python3 -c "
import json, os

config = {}
config_path = 'media_renamer_config.json'

# 读取已有配置
if os.path.exists(config_path):
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except Exception:
        config = {}

# 环境变量覆盖（MEDIA_RENAMER_ 前缀的变量由 pydantic-settings 自动读取）
# 这里手动写入文件，确保配置持久化
tmdb_key = os.environ.get('MEDIA_RENAMER_TMDB_API_KEY', '')
bgm_key = os.environ.get('MEDIA_RENAMER_BGM_API_KEY', '')

if tmdb_key:
    config['tmdb_api_key'] = tmdb_key
if bgm_key:
    config['bgm_api_key'] = bgm_key

# 写回配置文件
with open(config_path, 'w') as f:
    json.dump(config, f, ensure_ascii=False, indent=2)

print(f'配置已持久化 -> {config_path}')
if tmdb_key:
    print('  MEDIA_RENAMER_TMDB_API_KEY ✓')
if bgm_key:
    print('  MEDIA_RENAMER_BGM_API_KEY ✓')
"

# 启动主应用
exec "$@"