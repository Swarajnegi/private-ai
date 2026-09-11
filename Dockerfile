FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/js-development

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY js-development ./js-development
COPY scripts ./scripts
COPY .agent ./.agent
COPY js-learning ./js-learning
COPY knowledge ./knowledge
COPY README.md NERVOUS_SYSTEM.md AGENTS.md ./

RUN useradd --create-home --uid 10001 jarvis && chown -R jarvis:jarvis /app
USER jarvis
CMD ["python", "scripts/hosted_entrypoint.py"]
