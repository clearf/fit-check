FROM node:22-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    ca-certificates \
    python3 \
    python3-pip \
    python3-venv \
    openssh-client \
    neovim \
    screen \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Repurpose the existing 'node' user (UID 1000) as 'claude'.
# UID 1000 matches the typical Linux host user so volume-mounted files
# (e.g. ~/.claude.json, ~/.screenrc) are readable without chmod.
RUN usermod -l claude -d /home/claude -m -s /bin/bash node && \
    groupmod -n claude node

# Set up SSH directory for git operations (as root, then fix ownership)
RUN mkdir -p /home/claude/.ssh && \
    ssh-keyscan github.com >> /home/claude/.ssh/known_hosts 2>/dev/null && \
    chmod 700 /home/claude/.ssh && \
    chmod 644 /home/claude/.ssh/known_hosts && \
    chown -R claude:claude /home/claude/.ssh

# Copy entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENV EDITOR=nvim
ENV SHELL=/bin/bash

USER claude
WORKDIR /home/claude

ENTRYPOINT ["/bin/bash", "/usr/local/bin/docker-entrypoint.sh"]
