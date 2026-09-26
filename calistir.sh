#!/usr/bin/env bash
# YENİ NESİL CAFER'i başlatır
cd "$(dirname "$(readlink -f "$0")")" && exec .venv/bin/python main.py "$@"
