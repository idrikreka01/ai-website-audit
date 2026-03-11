FROM python:3.11-bookworm

WORKDIR /app

COPY api/requirements.txt ./api-requirements.txt
COPY worker/requirements.txt ./worker-requirements.txt
RUN pip install --no-cache-dir -r api-requirements.txt -r worker-requirements.txt
RUN playwright install --with-deps chromium

# Additional tools for debug / headed browser inside Docker (Xvfb + VNC + noVNC)
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    xvfb x11vnc fluxbox websockify git \
 && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/novnc/noVNC.git /opt/novnc && \
    ln -s /opt/novnc/vnc.html /opt/novnc/index.html

COPY . .
ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
