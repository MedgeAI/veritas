# SILA Dense Copy-Move Detection — HTTP Service
#
# Extends the existing veritas-sila-dense:latest image (Python 3.8 + OpenCV +
# compiled pm3D extension) with a FastAPI HTTP wrapper so the detection engine
# stays loaded in memory across requests.
#
# Build:  docker build -t veritas-sila-service:latest deploy/forensics/sila-dense/
# Run:    docker run -p 8770:8770 -v /path/to/project:/data veritas-sila-service

FROM veritas-sila-dense:latest

LABEL maintainer="Veritas"
LABEL description="SILA dense copy-move detection HTTP service"

# Install FastAPI + uvicorn + eval_type_backport (needed for Python 3.8 Pydantic).
RUN pip install --no-cache-dir fastapi uvicorn[standard] eval_type_backport

# Copy the service wrapper into the image.
WORKDIR /app
COPY app.py /app/app.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# curl for HEALTHCHECK.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8770

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8770/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
