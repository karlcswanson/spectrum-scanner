# Build stage - frontend
FROM node:20-alpine AS frontend
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build:standalone

# Build stage - Go binary
FROM golang:1.23-alpine AS builder
RUN apk add --no-cache git
WORKDIR /app
COPY scanner/go.mod scanner/go.sum ./
RUN go mod download
COPY scanner/ .
COPY --from=frontend /app/dist-standalone/ ./internal/api/web/
RUN mv internal/api/web/standalone.html internal/api/web/index.html
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o scanner ./cmd/scanner

# Runtime stage
FROM alpine:3.19
RUN apk add --no-cache ca-certificates tzdata
WORKDIR /app
COPY --from=builder /app/scanner .
EXPOSE 8080
ENTRYPOINT ["/app/scanner"]
CMD ["-listen", ":8080"]
