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
# Conversation history is intentionally part of the private hosted workspace.
# Do not copy the full data directory: vector indexes and machine-local state
# are rebuilt separately and must never inflate the deployment image.
COPY jarvis_data/conversations ./jarvis_data/conversations
COPY README.md NERVOUS_SYSTEM.md AGENTS.md ./

RUN useradd --create-home --uid 10001 jarvis && chown -R jarvis:jarvis /app
USER jarvis
CMD ["python", "scripts/hosted_entrypoint.py"]
