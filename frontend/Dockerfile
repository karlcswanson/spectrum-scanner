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

# This image just holds the static files
# They get copied to a shared volume in docker-compose
CMD ["cp", "-r", "/dist/.", "/srv/frontend/"]
