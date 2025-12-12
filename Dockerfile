FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER_PATH=/usr/bin/chromedriver \
    PORT=8000

# Install chromium and chromedriver with required dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      chromium \
      chromium-driver \
      ca-certificates \
      curl \
      fonts-liberation \
      libasound2 \
      libatk-bridge2.0-0 \
      libatk1.0-0 \
      libatspi2.0-0 \
      libcups2 \
      libdbus-1-3 \
      libdrm2 \
      libgbm1 \
      libgtk-3-0 \
      libnspr4 \
      libnss3 \
      libxcomposite1 \
      libxdamage1 \
      libxfixes3 \
      libxkbcommon0 \
      libxrandr2 \
      xdg-utils \
      libu2f-udev \
      libvulkan1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["bash", "-c", "gunicorn app:app --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 1 --timeout 180 --worker-class sync"]
