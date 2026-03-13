FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PYTHONPATH=/app
ENV PORT=8000

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl nodejs npm && rm -rf /var/lib/apt/lists/*

RUN npm install -g @modelcontextprotocol/server-sequential-thinking

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

RUN playwright install --with-deps chromium

COPY . /app

EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
