FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt && playwright install chromium --with-deps

COPY services/brotto-orchestrator/src ./src
COPY services/brotto-orchestrator/start_server.py .

ENV PYTHONPATH=/app/src
EXPOSE 8000

CMD ["python", "start_server.py"]
