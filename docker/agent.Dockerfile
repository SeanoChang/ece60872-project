FROM node:20-slim

RUN apt-get update && apt-get install -y \
    python3 python3-pip curl git openssh-client \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

RUN mkdir -p /workspace /root/.aws /root/.ssh
WORKDIR /workspace

COPY core/judge_hook.py /opt/bft-voting/core/judge_hook.py

# Hook config — only active inside this container, NOT on dev machine
RUN mkdir -p /root/.claude
COPY docker/claude-settings.json /root/.claude/settings.json

ENV ANTHROPIC_API_KEY=""
ENV ANTHROPIC_BASE_URL="http://host.docker.internal:8081"
ENV JUDGE_ORCHESTRATOR_URL="http://host.docker.internal:8080"
ENV PYTHONPATH="/opt/bft-voting"

CMD ["claude", "-p", "Set up this project and run the tests"]
