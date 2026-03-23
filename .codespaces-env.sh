#!/usr/bin/env bash

export OLLAMA_BASE_URL="https://billingonaire-ollama-s5cr5xt6wa-el.a.run.app"
export COURT_OLLAMA_BASE_URL="$OLLAMA_BASE_URL"
export LLM_BASE_URL="$OLLAMA_BASE_URL"

export COURT_OLLAMA_MODEL="llama3.1:8b"
export ORDER_LLM_MODEL="llama3.1:8b"
export LLM_MODEL="llama3.1:8b"
export ORDER_LLM_PROVIDER="ollama"