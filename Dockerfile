FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN printf 'precedence ::ffff:0:0/96  100\n' >> /etc/gai.conf

COPY pyproject.toml poetry.lock ./
RUN pip install --no-cache-dir poetry==2.4.1 \
    && POETRY_VIRTUALENVS_CREATE=false poetry install --only main --no-root --no-interaction

COPY app ./app
COPY data ./data

EXPOSE 5000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5000", "--proxy-headers"]
