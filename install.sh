#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
uv sync
mkdir -p ~/bin
ln -sf "$PWD/.venv/bin/agents" ~/bin/agents
echo "Installed: ~/bin/agents"
