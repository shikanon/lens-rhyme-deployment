FROM node:22-alpine AS build
ARG OPEN_WEBSEARCH_REVISION=a61bc65fc5edbf76b98bb81990e390b751617d01
WORKDIR /app
ADD https://codeload.github.com/Aas-ee/open-webSearch/tar.gz/${OPEN_WEBSEARCH_REVISION} /tmp/source.tar.gz
RUN tar -xzf /tmp/source.tar.gz --strip-components=1 -C /app && rm /tmp/source.tar.gz
# Lock patched compatible dependencies; do not run arbitrary install scripts or install a browser.
COPY package-lock.json ./package-lock.json
COPY patch-bing.mjs ./patch-bing.mjs
RUN node patch-bing.mjs
RUN npm ci --ignore-scripts && npm run build && npm prune --omit=dev --ignore-scripts && npm cache clean --force

FROM node:22-alpine
WORKDIR /app
COPY --from=build --chown=node:node /app/build ./build
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/package.json ./package.json
COPY --chown=node:node launch.mjs ./launch.mjs
USER node
ENV NODE_ENV=production SEARCH_MODE=request ALLOWED_SEARCH_ENGINES=bing,duckduckgo,exa,brave,startpage,hackernews
EXPOSE 3210
CMD ["node", "launch.mjs", "serve", "--host", "0.0.0.0", "--port", "3210"]
