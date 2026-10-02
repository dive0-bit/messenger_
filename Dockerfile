# One image runs the whole app: Django (REST API + WebSocket) and the web page (HTML, CSS, JS).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# psycopg is the Postgres driver. It is installed only here (Docker / Render),
# so the normal local setup does not need it.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "psycopg[binary]>=3.2"

COPY backend/ .

# collect admin css/js for WhiteNoise
RUN python manage.py collectstatic --noinput

EXPOSE 8000

# Render gives the port in $PORT (we use 8000 when it is not set).
# migrate creates/updates the database tables, then Daphne (ASGI: HTTP + WebSocket) starts.
CMD ["sh", "-c", "python manage.py migrate && daphne -b 0.0.0.0 -p ${PORT:-8000} config.asgi:application"]
