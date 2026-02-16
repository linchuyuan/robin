@echo off
set MCP_SERVER_MODE=1
python "%~dp0server.py" --transport=streamable-http --host=127.0.0.1 --port=8000 --path=/messages %*
