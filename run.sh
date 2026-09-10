#!/usr/bin/env bash
# 수집 + 분석 + 웹페이지 열기. 처음이면 .venv 를 만든다.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
fi
.venv/bin/python -m hotpost run --serve "$@"
