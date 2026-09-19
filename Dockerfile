# Build the Vite SPA on the target VPS, then serve only the immutable dist
# output from a small Nginx runtime image.
FROM oven/bun:1.3.11-alpine AS build

WORKDIR /app

# Install dependencies before copying application files so dependency layers
# can be reused when only frontend source files change.
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY . .

# These are public, build-time values. They are compiled into the browser
# bundle; never pass runtime secrets or credentials through these arguments.
ARG VITE_FASTAPI_URL
ARG VITE_ASSET_BASE_URL=/
ARG VITE_RELEASE_ID=dev
ARG VITE_WORKSPACE_ID=00000000-0000-0000-0000-000000000001
ARG VITE_SINGLE_WORKSPACE_MODE=true
ARG NEXT_PUBLIC_API_MODE=fastapi-direct
ARG NEXT_PUBLIC_USE_FASTAPI_BACKEND=1

ENV VITE_FASTAPI_URL=${VITE_FASTAPI_URL} \
    VITE_ASSET_BASE_URL=${VITE_ASSET_BASE_URL} \
    VITE_RELEASE_ID=${VITE_RELEASE_ID} \
    VITE_WORKSPACE_ID=${VITE_WORKSPACE_ID} \
    VITE_SINGLE_WORKSPACE_MODE=${VITE_SINGLE_WORKSPACE_MODE} \
    NEXT_PUBLIC_API_MODE=${NEXT_PUBLIC_API_MODE} \
    NEXT_PUBLIC_USE_FASTAPI_BACKEND=${NEXT_PUBLIC_USE_FASTAPI_BACKEND}

RUN test -n "$VITE_FASTAPI_URL" \
    && bun run build

FROM nginx:1.27-alpine

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

# The production release exporter runs with umask 077. Vite-generated files
# are readable by Nginx, but files copied from public/ can retain the source
# mode and become unreadable by the non-root Nginx worker. Normalize the
# complete static tree in the final image so every browser asset is public.
RUN find /usr/share/nginx/html -type d -exec chmod 755 {} \; \
    && find /usr/share/nginx/html -type f -exec chmod 644 {} \;

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=6 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz \
    && wget -q -O /dev/null http://127.0.0.1:8080/favicon.png
