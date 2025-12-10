.PHONY: build build-arm run dev deploy deploy-service clean tidy test

# Default target
all: build

# Build for local development (macOS/Linux)
build:
	go build -o bin/scanner ./cmd/scanner

# Cross-compile for ADALM Pluto (ARM)
build-arm:
	GOOS=linux GOARCH=arm GOARM=7 CGO_ENABLED=0 \
		go build -ldflags="-s -w" -o bin/scanner-arm ./cmd/scanner

# Development: run on Mac, talk to Plany uto over USB
dev:
	go run ./cmd/scanner \
		-listen :8080 \
		-maia https://192.168.2.1 \
		-config config.yaml

# Run with auto-start (for testing)
dev-auto:
	go run ./cmd/scanner \
		-listen :8080 \
		-maia https://192.168.2.1 \
		-config config.yaml \
		-auto-start

# Run locally built binary
run: build
	./bin/scanner -listen :8080 -maia https://192.168.2.1

# Deploy binary to Pluto via SSH (using legacy SCP protocol for Pluto compatibility)
deploy: build-arm
	scp -O bin/scanner-arm root@192.168.2.1:/usr/bin/spectrum-scanner
	ssh root@192.168.2.1 'chmod +x /usr/bin/spectrum-scanner'
	@echo "Deployed to Pluto. Run with: ssh root@192.168.2.1 '/usr/bin/spectrum-scanner'"

# Deploy and create init script for auto-start
deploy-service: deploy
	@echo "Creating init script on Pluto..."
	@echo '#!/bin/sh /etc/rc.common' > /tmp/spectrum-scanner.init
	@echo 'START=99' >> /tmp/spectrum-scanner.init
	@echo 'STOP=10' >> /tmp/spectrum-scanner.init
	@echo 'start() { echo "Starting spectrum-scanner..."; /usr/bin/spectrum-scanner -listen :8080 -maia https://localhost -auto-start & }' >> /tmp/spectrum-scanner.init
	@echo 'stop() { echo "Stopping spectrum-scanner..."; killall spectrum-scanner 2>/dev/null; }' >> /tmp/spectrum-scanner.init
	@echo 'restart() { stop; sleep 1; start; }' >> /tmp/spectrum-scanner.init
	scp -O /tmp/spectrum-scanner.init root@192.168.2.1:/etc/init.d/spectrum-scanner
	ssh root@192.168.2.1 'chmod +x /etc/init.d/spectrum-scanner'
	@rm /tmp/spectrum-scanner.init
	@echo "Init script created. Enable with: ssh root@192.168.2.1 '/etc/init.d/spectrum-scanner enable'"

# Start service on Pluto
start-remote:
	ssh root@192.168.2.1 '/etc/init.d/spectrum-scanner start'

# Stop service on Pluto
stop-remote:
	ssh root@192.168.2.1 '/etc/init.d/spectrum-scanner stop'

# View logs on Pluto (if using syslog)
logs:
	ssh root@192.168.2.1 'logread | grep spectrum-scanner | tail -50'

# Check if Pluto is reachable
check-pluto:
	@ping -c 1 192.168.2.1 > /dev/null 2>&1 && echo "Pluto is reachable at 192.168.2.1" || echo "Pluto not found at 192.168.2.1"

# Check maia-httpd status on Pluto
check-maia:
	@curl -s http://192.168.2.1:8080/api/ad9361 | head -c 100 && echo "..." || echo "maia-httpd not responding"

# Download dependencies
tidy:
	go mod tidy

# Run tests
test:
	go test -v ./...

# Clean build artifacts
clean:
	rm -rf bin/

# Show help
help:
	@echo "Spectrum Scanner Build Commands:"
	@echo ""
	@echo "Development:"
	@echo "  make build      - Build for local machine"
	@echo "  make dev        - Run locally, connect to Pluto at 192.168.2.1"
	@echo "  make dev-auto   - Run locally with auto-start scanning"
	@echo "  make test       - Run tests"
	@echo ""
	@echo "Deployment:"
	@echo "  make build-arm      - Cross-compile for Pluto (ARM)"
	@echo "  make deploy         - Deploy binary to Pluto via SSH"
	@echo "  make deploy-service - Deploy with init script for auto-start"
	@echo ""
	@echo "Remote Control:"
	@echo "  make start-remote - Start scanner on Pluto"
	@echo "  make stop-remote  - Stop scanner on Pluto"
	@echo "  make logs         - View scanner logs on Pluto"
	@echo ""
	@echo "Utilities:"
	@echo "  make check-pluto  - Check if Pluto is reachable"
	@echo "  make check-maia   - Check if maia-httpd is running"
	@echo "  make clean        - Remove build artifacts"
	@echo "  make tidy         - Download Go dependencies"
