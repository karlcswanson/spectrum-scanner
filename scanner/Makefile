.PHONY: build build-arm build-glinet run dev deploy deploy-service clean tidy test build-frontend desktop desktop-deps desktop-mac desktop-windows desktop-linux desktop-dev calibrate help

# Default target
all: build

# Build Vue frontend for standalone scanner
build-frontend:
	cd ../frontend && npm run build:standalone
	rm -rf internal/api/web/assets internal/api/web/index.html
	cp -r ../frontend/dist-standalone/* internal/api/web/
	mv internal/api/web/standalone.html internal/api/web/index.html
	@echo "Frontend built and copied to internal/api/web/"

# Build for local development (macOS/Linux)
build: build-frontend
	go build -o bin/scanner ./cmd/scanner

# Cross-compile for ADALM Pluto (ARM)
build-arm: build-frontend
	GOOS=linux GOARCH=arm GOARM=7 CGO_ENABLED=0 \
		go build -ldflags="-s -w" -o bin/scanner-arm ./cmd/scanner

# Cross-compile for GL.iNet Spitz AX / ARM64 routers
build-glinet: build-frontend
	GOOS=linux GOARCH=arm64 CGO_ENABLED=0 \
		go build -ldflags="-s -w" -o bin/scanner-glinet ./cmd/scanner

# Build calibration tool
calibrate:
	go build -o bin/calibrate ./cmd/calibrate

# Build everything: frontend + ARM binary (for deployment)
build-all: build-arm
	@echo "Built frontend and ARM binary"

# Build all local tools
build-local: build calibrate
	@echo "Built local binaries"

# ============== Desktop App (Wails) ==============

# Install desktop frontend dependencies
desktop-deps:
	cd cmd/desktop/frontend && npm install

# Build desktop app for current platform
desktop: desktop-deps
	cd cmd/desktop && wails build

# Build desktop app for macOS (universal binary)
desktop-mac: desktop-deps
	cd cmd/desktop && wails build -platform darwin/universal

# Build desktop app for Windows
desktop-windows: desktop-deps
	cd cmd/desktop && wails build -platform windows/amd64

# Build desktop app for Linux
desktop-linux: desktop-deps
	cd cmd/desktop && wails build -platform linux/amd64

# Run desktop app in dev mode
desktop-dev: desktop-deps
	cd cmd/desktop && wails dev

# Development: run on Mac, talk to Pluto over USB
dev:
	go run ./cmd/scanner \
		-listen :8080 \
		-addr https://192.168.2.1

# Run locally built binary
run: build
	./bin/scanner -listen :8080 -addr https://192.168.2.1

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
	@echo 'start() { echo "Starting spectrum-scanner..."; /usr/bin/spectrum-scanner -listen :8080 -addr https://localhost & }' >> /tmp/spectrum-scanner.init
	@echo 'stop() { echo "Stopping spectrum-scanner..."; killall spectrum-scanner 2>/dev/null; }' >> /tmp/spectrum-scanner.init
	@echo 'restart() { stop; sleep 1; start; }' >> /tmp/spectrum-scanner.init
	scp -O /tmp/spectrum-scanner.init root@192.168.2.1:/etc/init.d/spectrum-scanner
	ssh root@192.168.2.1 'chmod +x /etc/init.d/spectrum-scanner'
	@rm -f /tmp/spectrum-scanner.init
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
	rm -rf cmd/desktop/build/bin/
	rm -rf internal/api/web/assets/
	rm -f internal/api/web/index.html

# Show help
help:
	@echo "Spectrum Scanner Build Commands:"
	@echo ""
	@echo "Development:"
	@echo "  make build          - Build scanner for local machine"
	@echo "  make calibrate      - Build calibration tool"
	@echo "  make build-local    - Build all local tools (scanner + calibrate)"
	@echo "  make dev            - Run locally, connect to Pluto at 192.168.2.1"
	@echo "  make test           - Run tests"
	@echo ""
	@echo "Frontend:"
	@echo "  make build-frontend - Build Vue standalone app"
	@echo "  make build-all      - Build frontend + ARM binary"
	@echo ""
	@echo "Desktop App (Wails):"
	@echo "  make desktop        - Build for current platform"
	@echo "  make desktop-mac    - Build for macOS (universal)"
	@echo "  make desktop-windows- Build for Windows"
	@echo "  make desktop-linux  - Build for Linux"
	@echo "  make desktop-dev    - Run in development mode"
	@echo ""
	@echo "Deployment:"
	@echo "  make build-arm      - Cross-compile for Pluto (ARMv7)"
	@echo "  make build-glinet   - Cross-compile for GL.iNet Spitz AX (ARM64)"
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
