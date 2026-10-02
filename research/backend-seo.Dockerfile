# Targeted SEO-only update over the verified existing application release.
# No dependencies change: the research adapter, parsers and tools use the standard library.
ARG BACKEND_BASE_IMAGE
FROM ${BACKEND_BASE_IMAGE}
ARG SOURCE_REVISION
LABEL org.opencontainers.image.revision=${SOURCE_REVISION}
COPY core/seo_content /app/core/seo_content
COPY scripts/api/admin_content_generation_control.py /app/scripts/api/admin_content_generation_control.py
COPY migrations/versions /app/migrations/versions
COPY build_tools/protect_python_sources.py /app/build_tools/protect_python_sources.py
RUN python /app/build_tools/protect_python_sources.py build --remove-sources
