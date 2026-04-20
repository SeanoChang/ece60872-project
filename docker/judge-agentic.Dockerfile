# Agentic judge container — Claude Code with investigation capabilities.
# Stays alive for the entire experiment. Work arrives via docker exec.

FROM node:20-slim

# System tools for investigation
RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    curl git openssh-client \
    jq grep ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code
RUN npm install -g @anthropic-ai/claude-code

# Create directory structure
RUN mkdir -p /judge /workspace /sandbox
WORKDIR /judge

# Baseline Claude Code settings for judges. Carries model default +
# permissions.defaultMode=bypassPermissions so `claude -p` doesn't stall on
# interactive permission prompts (which can't be answered in -p mode).
# Loaded when agentic_judge passes --setting-sources user.
RUN mkdir -p /root/.claude
COPY docker/judge-settings.json /root/.claude/settings.json

# Environment — proxy handles API key
ENV ANTHROPIC_API_KEY="proxied"
ENV ANTHROPIC_BASE_URL="http://host.docker.internal:8081"

# Container stays alive, work arrives via docker exec
CMD ["sleep", "infinity"]
