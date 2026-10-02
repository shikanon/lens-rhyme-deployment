FROM python:3.12-slim
ARG AGENT_REACH_REVISION=a19a171fa980a0785849596492e0af4db800c82f
LABEL org.opencontainers.image.source=https://github.com/Panniantong/Agent-Reach
LABEL org.opencontainers.image.revision=${AGENT_REACH_REVISION}
# Official repository only; the similarly named PyPI package is unrelated.
RUN pip install --no-cache-dir requests==2.32.5 feedparser==6.0.12 python-dotenv==1.2.1 loguru==0.7.3 pyyaml==6.0.3 rich==14.3.3 && \
    pip install --no-cache-dir --no-deps https://codeload.github.com/Panniantong/Agent-Reach/tar.gz/${AGENT_REACH_REVISION}
RUN useradd --uid 10001 --create-home reader
WORKDIR /app
COPY server.py /app/server.py
USER reader
EXPOSE 3211
CMD ["python", "/app/server.py"]
