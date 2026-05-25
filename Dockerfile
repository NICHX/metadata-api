# ---- Builder ----
FROM python:3.11-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ---- Runtime ----
FROM python:3.11-slim

WORKDIR /app

# 时区
ENV TZ=Asia/Shanghai

# 环境变量（运行时可通过 -e 覆盖）
#   METADATA_TMDB_API_KEY    TMDb API 密钥（必填）
#   METADATA_BGM_API_KEY     Bangumi API 密钥（可选）
#   METADATA_MODE            部署模式: local / remote（默认 local）

# 从 builder 复制 Python 依赖
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# 复制启动入口脚本
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# 复制项目代码
COPY . .

# 端口
EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python3", "main_api.py", "--host", "0.0.0.0", "--port", "8000"]