# Stage 1: Build frontend
FROM node:22-alpine AS frontend-builder

# Cache bust: rebuild frontend when git commit changes
ARG BUILD_VERSION=dev

WORKDIR /build
COPY web/frontend/package*.json ./
# --legacy-peer-deps: 允许 @testing-library/react peer dep 与 react 18/19 的松散匹配
# lockfile 在本地 npm 宽松模式下生成，Docker 的 npm 10 默认更严格
RUN npm ci --silent --legacy-peer-deps

COPY web/frontend/ ./
RUN npm run build && echo "Built version: ${BUILD_VERSION}"

# Stage 2: Python runtime
FROM node:22-bookworm-slim

# Create non-root user matching host UID/GID for bind mount compatibility
ARG USERNAME=veritas
ARG USER_UID=1000
ARG USER_GID=1000

# Install Python and system dependencies for static audit/image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    libgl1 \
    libglib2.0-0 \
    python3 \
    python3-pip \
    python3-venv \
    tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid $USER_GID $USERNAME 2>/dev/null \
       || groupmod -n $USERNAME $(getent group $USER_GID | cut -d: -f1) 2>/dev/null \
       || true \
    && useradd --uid $USER_UID --gid $USER_GID --shell /bin/bash --create-home $USERNAME 2>/dev/null \
       || usermod -l $USERNAME -d /home/$USERNAME -m $(getent passwd $USER_UID | cut -d: -f1) 2>/dev/null \
       || true

ARG OPENCODE_NPM_PACKAGE=opencode-ai@1.17.11
RUN npm install -g "${OPENCODE_NPM_PACKAGE}"

# Install uv for deterministic dependency resolution from uv.lock
# Pinned version prevents surprise breakages on image rebuild
# Binary placed in /usr/local/bin (in PATH for all users including non-root)
ARG UV_VERSION=0.6.14
RUN curl -LsSf "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz" \
    | tar xz -C /tmp \
    && mv /tmp/uv-x86_64-unknown-linux-gnu/uv /usr/local/bin/uv \
    && chmod +x /usr/local/bin/uv \
    && rm -rf /tmp/uv-*

ENV VIRTUAL_ENV=/opt/venv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
ENV VERITAS_HOST=0.0.0.0
ENV VERITAS_PORT=8765
ENV VERITAS_DATA_ROOT=/app/web_data
ENV VERITAS_OUTPUT_ROOT=/app/outputs
ENV VERITAS_OPENCODE_BIN=opencode
ENV VERITAS_LOG_DIR=/app/logs

WORKDIR /app

# ── Directory layout: code vs data boundary ─────────────────────────
# /app/                 — application code (read-only for veritas)
# /app/web_data/        — runtime data root (veritas-writable, bind mount target)
# /app/outputs/         — audit artifacts (veritas-writable, bind mount target)
# /app/logs/            — log files (veritas-writable)
#
# chmod 777 /app: allows veritas to create project-local directories
#   (e.g. .opencode/ for opencode session data). The code COPY'd into
#   /app/ is root:root 755 — readable but not writable by veritas.
# This is a tiny layer (just the directory entry, not recursive).
RUN mkdir -p /app/web_data /app/outputs /app/logs \
    && chmod 777 /app /app/logs

# Install Python dependencies (from pyproject.toml + uv.lock)
# Dependency files are copied BEFORE source code: if only source changes,
# the uv sync layer stays cached (the most expensive layer ~309MB).
COPY pyproject.toml uv.lock ./
COPY cli/ ./cli/
COPY engine/ ./engine/
COPY runtime/ ./runtime/
COPY configs/ ./configs/
COPY web/backend/ ./web/backend/
COPY scripts/ ./scripts/
# Audit-critical third-party adapters. See .dockerignore for why only these subdirs.
# research-integrity-auditor: MinerU convert, evidence ledger, numeric forensics scripts.
# elis/system_modules: panel-extractor (YOLOv5), copy-move (RootSIFT/SILA), TruFor.
# paperconan: GRIM/GRIMMER numeric forensics (imported via sys.path in adapter).
COPY third_party/research-integrity-auditor/ ./third_party/research-integrity-auditor/
COPY third_party/elis/system_modules/ ./third_party/elis/system_modules/
COPY third_party/paperconan/ ./third_party/paperconan/
COPY opencode.json .
COPY .opencode/skills/ ./.opencode/skills/
COPY README.md .

# ── Runtime data: code vs data separation ───────────────────────────
# .opencode/ is created by COPY above (root:root). opencode writes session
# data to .opencode/data/ at runtime. We redirect this to web_data/ via symlink
# so all runtime-writable state lives under the data volume.
#
# Layout:
#   /app/.opencode/skills/          — read-only, root:root (image code)
#   /app/.opencode/data -> symlink  — points to /app/web_data/.opencode/data
#   /app/web_data/.opencode/data/   — veritas:veritas (runtime data volume)
RUN mkdir -p /app/web_data/.opencode/data /app/outputs \
    && chown -R $USERNAME:$USERNAME /app/web_data /app/outputs \
    && chown $USERNAME:$USERNAME /app/.opencode \
    && ln -s /app/web_data/.opencode/data /app/.opencode/data
# uv sync --frozen: install exactly what uv.lock specifies, no resolution drift
# --no-cache: skip uv's cache to keep image layers lean
# UV_PROJECT_ENVIRONMENT (set above) tells uv to install into /opt/venv,
# preventing it from creating its own .venv in the project directory
RUN uv sync --frozen --extra web --extra pg --extra visual --no-cache

# Copy frontend build artifacts from stage 1
COPY --from=frontend-builder /build/dist ./web/frontend/dist

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV VERITAS_HOST=0.0.0.0
ENV VERITAS_PORT=8765

# Set timezone
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Switch to non-root user
USER $USERNAME

# Health check
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8765/api/health || exit 1

# Expose port and start command
EXPOSE 8765
CMD ["python", "-m", "web.backend.veritas_web.app"]
