FROM python:3.11-slim

WORKDIR /app

COPY mcp_compliance_server.py mcp_config.json ./

# 零外部依赖：优先用官方 mcp 库（装了就更好），没装也能跑内置 stdio JSON-RPC。
# 若希望使用官方库，取消下面这行的注释：
# RUN pip install --no-cache-dir mcp fastmcp

CMD ["python", "mcp_compliance_server.py"]