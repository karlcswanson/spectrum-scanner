# Build stage
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci

# Copy source
COPY . .

# Build production bundle
RUN npm run build

# Production stage - just the static files
FROM alpine:latest AS production

# Copy built files to a directory that can be mounted
COPY --from=builder /app/dist /dist
COPY publish.sh /publish.sh
RUN chmod +x /publish.sh

# On start: inject the ANALYTICS_EMBED snippet (runtime env, optional) into
# index.html, then copy the static build to the shared volume.
CMD ["/publish.sh"]
