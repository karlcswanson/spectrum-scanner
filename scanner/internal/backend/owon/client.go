// Package owon implements the scanner backend for OWON HSA1000 series spectrum analyzers.
// Communication is via SCPI commands over TCP socket on port 5188.
package owon

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"log"
	"net"
	"strconv"
	"strings"
	"sync"
	"time"

	"scanner/internal/models"
	"scanner/internal/scanner"
)

const (
	// DefaultPort is the SCPI port for OWON spectrum analyzers
	// Note: Some models use 5188, others use 1015
	DefaultPort = 1015

	// DefaultTimeout for SCPI commands
	DefaultTimeout = 5 * time.Second

	// TracePoints is the default number of points in a trace (HSA1016)
	// Actual value is queried from device on connect
	TracePoints = 461
)

// Client implements scanner.Backend for OWON HSA1000 series spectrum analyzers.
type Client struct {
	address string
	port    int
	name    string

	mu        sync.Mutex
	conn      net.Conn
	reader    *bufio.Reader
	connected bool

	// Device info (populated on connect)
	info scanner.BackendInfo
}

// NewClient creates a new OWON spectrum analyzer client.
func NewClient(address string, port int, name string) *Client {
	if port == 0 {
		port = DefaultPort
	}
	if name == "" {
		name = "OWON HSA1016"
	}
	return &Client{
		address: address,
		port:    port,
		name:    name,
	}
}

// Name returns the scanner name
func (c *Client) Name() string {
	return c.name
}

// Type returns the backend type
func (c *Client) Type() string {
	return "owon"
}

// FrequencyRange returns the frequency range this scanner supports
func (c *Client) FrequencyRange() (minHz, maxHz int64) {
	// HSA1016-TG: 9 kHz to 1.6 GHz
	return 9_000, 1_600_000_000
}

// Connect is a no-op for OWON - we connect per-sweep to allow front panel access between sweeps
func (c *Client) Connect() error {
	log.Printf("OWON: Backend ready (will connect to %s:%d when scanning)", c.address, c.port)
	return nil
}

// connect is the internal connect method (caller must hold mutex)
func (c *Client) connect() error {
	if c.connected {
		return nil
	}

	addr := fmt.Sprintf("%s:%d", c.address, c.port)

	conn, err := net.DialTimeout("tcp", addr, DefaultTimeout)
	if err != nil {
		return fmt.Errorf("failed to connect to OWON at %s: %w", addr, err)
	}

	c.conn = conn
	c.reader = bufio.NewReader(conn)
	c.connected = true

	// Query device identification
	idn, err := c.query("*IDN?")
	if err != nil {
		c.conn.Close()
		c.connected = false
		return fmt.Errorf("failed to query device ID: %w", err)
	}

	// Parse IDN response: "Manufacturer,Model,Serial,Firmware"
	parts := strings.Split(strings.TrimSpace(idn), ",")
	if len(parts) >= 4 {
		c.info = scanner.BackendInfo{
			Type:         "owon",
			Manufacturer: strings.TrimSpace(parts[0]),
			Model:        strings.TrimSpace(parts[1]),
			Serial:       strings.TrimSpace(parts[2]),
			Firmware:     strings.TrimSpace(parts[3]),
		}
	}

	log.Printf("OWON: Connected to %s %s (S/N: %s, FW: %s)",
		c.info.Manufacturer, c.info.Model, c.info.Serial, c.info.Firmware)

	return nil
}

// Close disconnects from the spectrum analyzer (if connected)
func (c *Client) Close() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.connected {
		return c.close()
	}
	return nil
}

// close is the internal close method (caller must hold mutex)
func (c *Client) close() error {
	if !c.connected {
		return nil
	}

	c.connected = false
	if c.conn != nil {
		err := c.conn.Close()
		c.conn = nil
		c.reader = nil
		return err
	}
	return nil
}

// IsConnected returns whether the client is connected
func (c *Client) IsConnected() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.connected
}

// Configure is a no-op for OWON - we just read whatever the device is currently displaying.
// Use the OWON's front panel to configure frequency range, RBW, etc.
func (c *Client) Configure(band models.Band, settings scanner.SweepSettings) error {
	// No-op - OWON is configured via front panel
	return nil
}

// Sweep connects, reads the current trace from the OWON display, then disconnects
// This allows you to adjust settings on the front panel between sweeps
func (c *Client) Sweep(ctx context.Context) (models.ScanLine, error) {
	select {
	case <-ctx.Done():
		return models.ScanLine{}, ctx.Err()
	default:
	}

	// Connect, read, disconnect - all within the lock
	c.mu.Lock()
	defer c.mu.Unlock()

	// Connect for this sweep
	if err := c.connect(); err != nil {
		return models.ScanLine{}, fmt.Errorf("connect: %w", err)
	}
	// Disconnect after sweep to unlock front panel
	defer c.close()

	// Query current frequency settings from the device
	startResp, err := c.query(":FREQ:STAR?")
	if err != nil {
		return models.ScanLine{}, fmt.Errorf("query start freq: %w", err)
	}
	startHz, err := strconv.ParseInt(strings.TrimSpace(startResp), 10, 64)
	if err != nil {
		return models.ScanLine{}, fmt.Errorf("parse start freq: %w", err)
	}

	stopResp, err := c.query(":FREQ:STOP?")
	if err != nil {
		return models.ScanLine{}, fmt.Errorf("query stop freq: %w", err)
	}
	stopHz, err := strconv.ParseInt(strings.TrimSpace(stopResp), 10, 64)
	if err != nil {
		return models.ScanLine{}, fmt.Errorf("parse stop freq: %w", err)
	}

	// Query trace data (reads whatever is currently on screen)
	response, err := c.query(":TRACe:DATA? TRACe1")
	if err != nil {
		return models.ScanLine{}, fmt.Errorf("query trace: %w", err)
	}

	// Parse trace data
	powers, err := parseTraceData(response)
	if err != nil {
		return models.ScanLine{}, fmt.Errorf("parse trace: %w", err)
	}

	// Calculate step size based on span and points
	totalSpan := float64(stopHz - startHz)
	stepHz := totalSpan / float64(len(powers)-1)

	return models.ScanLine{
		Timestamp: time.Now().UTC(),
		HzLo:      float64(startHz),
		HzHi:      float64(stopHz),
		Step:      stepHz,
		Samples:   float64(len(powers)),
		Power:     powers,
	}, nil
}

// send writes a SCPI command to the device
func (c *Client) send(cmd string) error {
	if c.conn == nil {
		return fmt.Errorf("not connected")
	}

	c.conn.SetWriteDeadline(time.Now().Add(DefaultTimeout))
	_, err := fmt.Fprintf(c.conn, "%s\n", cmd)
	if err != nil {
		return fmt.Errorf("write command %q: %w", cmd, err)
	}

	return nil
}

// query sends a command and reads the response
func (c *Client) query(cmd string) (string, error) {
	return c.queryWithTimeout(cmd, DefaultTimeout)
}

// queryWithTimeout sends a command and reads the response with a custom timeout
func (c *Client) queryWithTimeout(cmd string, timeout time.Duration) (string, error) {
	if err := c.send(cmd); err != nil {
		return "", err
	}

	c.conn.SetReadDeadline(time.Now().Add(timeout))
	response, err := c.reader.ReadString('\n')
	if err != nil && err != io.EOF {
		return "", fmt.Errorf("read response: %w", err)
	}

	return strings.TrimSpace(response), nil
}

// parseTraceData parses the OWON trace response format
// Format: #9<9-digit-length><comma-separated-values>
// Example: #9000004807,-64.7301,-68.163,...,-36.195,-57.951
func parseTraceData(response string) ([]float64, error) {
	// Check for IEEE 488.2 definite length block format
	if len(response) < 2 || response[0] != '#' {
		// Try parsing as simple comma-separated values
		return parseCSVTrace(response)
	}

	// Parse #N<N-digits><data> format
	if len(response) < 3 {
		return nil, fmt.Errorf("response too short")
	}

	// Get number of length digits
	numDigits := int(response[1] - '0')
	if numDigits < 1 || numDigits > 9 {
		// Might be simple format, try CSV
		return parseCSVTrace(response)
	}

	if len(response) < 2+numDigits {
		return nil, fmt.Errorf("response too short for header")
	}

	// Get data length
	lengthStr := response[2 : 2+numDigits]
	dataLength, err := strconv.Atoi(lengthStr)
	if err != nil {
		return nil, fmt.Errorf("parse data length %q: %w", lengthStr, err)
	}

	// Extract data portion
	dataStart := 2 + numDigits
	if len(response) < dataStart+dataLength {
		// Data might be truncated, try to parse what we have
		log.Printf("OWON: Warning - expected %d bytes, got %d", dataLength, len(response)-dataStart)
	}

	data := response[dataStart:]
	return parseCSVTrace(data)
}

// parseCSVTrace parses comma-separated dBm values
func parseCSVTrace(data string) ([]float64, error) {
	parts := strings.Split(data, ",")
	if len(parts) == 0 {
		return nil, fmt.Errorf("no data points")
	}

	power := make([]float64, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		val, err := strconv.ParseFloat(p, 64)
		if err != nil {
			log.Printf("OWON: Warning - failed to parse value %q: %v", p, err)
			continue
		}
		power = append(power, val)
	}

	if len(power) == 0 {
		return nil, fmt.Errorf("no valid data points parsed")
	}

	return power, nil
}

// Info returns information about the connected device
func (c *Client) Info() scanner.BackendInfo {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.info
}

// GetCapabilities returns the capabilities of this scanner
func (c *Client) GetCapabilities() scanner.Capabilities {
	return scanner.Capabilities{
		MinFreqHz:            9_000,
		MaxFreqHz:            1_600_000_000,
		RBWOptions:           []int64{1, 3, 10, 30, 100, 300, 1000, 3000, 10000, 30000, 100000, 300000, 1000000}, // Hz
		HasTrackingGenerator: true,                                                                               // HSA1016-TG has TG
		HasAttenuation:       true,
		MinAttenuationDB:     0,
		MaxAttenuationDB:     40,
		HasGainControl:       false,
		TracePoints:          TracePoints,
	}
}
