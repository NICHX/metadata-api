#!/bin/sh
set -e

# 创建数据目录（卷挂载点）
mkdir -p /app/data

# 将环境变量写入配置文件，确保配置持久化
python3 -c "
import json, os

DATA_DIR = 'data'
config_path = os.path.join(DATA_DIR, 'metadata_api_config.json')

# 读取已有配置
config = {}
if os.path.exists(config_path):
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except Exception:
        config = {}

# METADATA_ 前缀的环境变量映射到配置文件的 key 名
# 注意：auth_key、ai_api_key、web_username、web_password 等敏感凭据
# 只通过环境变量注入，不写入配置文件
ENV_MAP = {
    'METADATA_TMDB_API_KEY': 'tmdb_api_key',
    'METADATA_BGM_API_KEY': 'bgm_api_key',
    'METADATA_AI_BASE_URL': 'ai_base_url',
    'METADATA_AI_MODEL': 'ai_model',
}

printed = []
for env_key, config_key in ENV_MAP.items():
    val = os.environ.get(env_key, '')
    if val:
        config[config_key] = val
        printed.append(f'  {env_key} \u2713')
    elif config_key not in config:
        # 环境变量未设置且配置文件中也没有，使用默认值
        defaults = {
            'ai_base_url': 'https://api.deepseek.com',
            'ai_model': 'deepseek-v4-flash',
        }
        if config_key in defaults:
            config[config_key] = defaults[config_key]

# MEDIA_LIBRARY 由 pydantic-settings 通过 METADATA_MEDIA_LIBRARY 别名读取
# 但 docker-compose 中使用的是 MEDIA_LIBRARY，单独处理
media_lib = os.environ.get('MEDIA_LIBRARY', '')
if media_lib:
    config['media_library'] = media_lib
    printed.append('  MEDIA_LIBRARY \u2713')

# 写回配置文件
os.makedirs(DATA_DIR, exist_ok=True)
with open(config_path, 'w') as f:
    json.dump(config, f, ensure_ascii=False, indent=2)

print(f'配置已持久化 -> {config_path}')
for line in printed:
    print(line)
if not printed:
    print('  （未从环境变量读取到任何配置项）')

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