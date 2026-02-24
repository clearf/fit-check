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
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Create a non-root user for running Claude
RUN useradd -m -s /bin/bash claude

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

USER claude
WORKDIR /home/claude

ENTRYPOINT ["/bin/bash", "/usr/local/bin/docker-entrypoint.sh"]
