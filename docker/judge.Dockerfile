FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    git curl npm \
    && rm -rf /var/lib/apt/lists/*

RUN pip install anthropic httpx

RUN mkdir -p /workspace /sandbox
WORKDIR /sandbox

COPY core/judge_agent.py /opt/bft-voting/core/judge_agent.py
COPY core/types.py /opt/bft-voting/core/types.py
COPY core/__init__.py /opt/bft-voting/core/__init__.py

ENV PYTHONPATH="/opt/bft-voting"
ENV ANTHROPIC_API_KEY=""
ENV ANTHROPIC_BASE_URL="http://host.docker.internal:8081"
