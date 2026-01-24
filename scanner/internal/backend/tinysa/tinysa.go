// Package tinysa provides a driver for the tinySA Ultra spectrum analyzer/signal generator.
package tinysa

import (
	"bufio"
	"fmt"
	"log"
	"strings"
	"time"

	"go.bug.st/serial"
)

// Device represents a connection to a tinySA Ultra
type Device struct {
	port     serial.Port
	reader   *bufio.Reader
	portName string
	debug    bool
}

// Config holds connection settings
type Config struct {
	Port     string // Serial port (e.g., "/dev/tty.usbmodem4001")
	BaudRate int    // Default: 576000
	Debug    bool   // Log commands and responses
}

// DefaultConfig returns default connection settings
func DefaultConfig() Config {
	return Config{
		Port:     "/dev/tty.usbmodem4001",
		BaudRate: 576000,
		Debug:    false,
	}
}

// Open connects to the tinySA
func Open(cfg Config) (*Device, error) {
	if cfg.BaudRate == 0 {
		cfg.BaudRate = 576000
	}

	mode := &serial.Mode{
		BaudRate: cfg.BaudRate,
		DataBits: 8,
		Parity:   serial.NoParity,
		StopBits: serial.OneStopBit,
	}

	port, err := serial.Open(cfg.Port, mode)
	if err != nil {
		return nil, fmt.Errorf("failed to open serial port %s: %w", cfg.Port, err)
	}

	port.SetReadTimeout(2 * time.Second)

	d := &Device{
		port:     port,
		reader:   bufio.NewReader(port),
		portName: cfg.Port,
		debug:    cfg.Debug,
	}

	// Clear any pending data
	d.sendCommand("")

	return d, nil
}

// Close closes the connection
func (d *Device) Close() error {
	if d.port != nil {
		return d.port.Close()
	}
	return nil
}

// sendCommand sends a command and reads the response
func (d *Device) sendCommand(cmd string) (string, error) {
	if d.debug && cmd != "" {
		log.Printf("tinySA cmd: %s", cmd)
	}

	_, err := d.port.Write([]byte(cmd + "\r\n"))
	if err != nil {
		return "", err
	}

	time.Sleep(100 * time.Millisecond)

	// Read response
	d.port.SetReadTimeout(200 * time.Millisecond)
	buf := make([]byte, 1024)
	n, _ := d.port.Read(buf)

	resp := ""
	if n > 0 {
		resp = strings.TrimSpace(string(buf[:n]))
		if d.debug && resp != "" && resp != cmd {
			log.Printf("tinySA resp: %s", resp)
		}
	}

	return resp, nil
}

// =============================================================================
// Spectrum Analyzer (Input) Mode
// =============================================================================

// InputOn switches to spectrum analyzer (input) mode
func (d *Device) InputOn() error {
	_, err := d.sendCommand("mode input")
	time.Sleep(500 * time.Millisecond)
	return err
}

// SetSweepRange sets the sweep start and stop frequencies in Hz
func (d *Device) SetSweepRange(startHz, stopHz float64) error {
	d.sendCommand(fmt.Sprintf("sweep start %d", int64(startHz)))
	time.Sleep(50 * time.Millisecond)
	_, err := d.sendCommand(fmt.Sprintf("sweep stop %d", int64(stopHz)))
	return err
}

// SetRBW sets the resolution bandwidth in kHz
// Valid values: 3, 10, 30, 100, 300, 600
func (d *Device) SetRBW(rbwKHz int) error {
	_, err := d.sendCommand(fmt.Sprintf("rbw %d", rbwKHz))
	return err
}

// =============================================================================
// General Commands
// =============================================================================

// Resume resumes sweeping
func (d *Device) Resume() error {
	_, err := d.sendCommand("resume")
	return err
}

// GetVersion returns the firmware version string
func (d *Device) GetVersion() (string, error) {
	return d.sendCommand("version")
}

// SetAttenuation sets internal attenuation (0-31 dB)
func (d *Device) SetAttenuation(db int) error {
	_, err := d.sendCommand(fmt.Sprintf("attenuate %d", db))
	return err
}

// =============================================================================
// Sweep Data Acquisition
// =============================================================================

// ReadSweep performs a sweep and returns power values in dBm
func (d *Device) ReadSweep() ([]float64, error) {
	// Use 'data 0' command which returns ASCII level values
	_, err := d.port.Write([]byte("data 0\r\n"))
	if err != nil {
		return nil, fmt.Errorf("failed to send data command: %w", err)
	}

	// Wait for response
	time.Sleep(100 * time.Millisecond)
	d.port.SetReadTimeout(3 * time.Second)

	// Read response - may need multiple reads for all data
	var allData []byte
	buf := make([]byte, 4096)
	for {
		n, err := d.port.Read(buf)
		if n > 0 {
			allData = append(allData, buf[:n]...)
		}
		if err != nil || n == 0 {
			break
		}
		// Short delay between reads
		time.Sleep(50 * time.Millisecond)
	}

	if len(allData) == 0 {
		return nil, fmt.Errorf("no data received from tinySA")
	}

	// Parse ASCII response - each line is a level value
	lines := strings.Split(string(allData), "\n")
	var powers []float64

	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line == "" || line == "data 0" || strings.HasPrefix(line, "ch>") {
			continue
		}

		// Parse the level value - tinySA Ultra returns values already in dBm
		var level float64
		if _, err := fmt.Sscanf(line, "%f", &level); err == nil {
			powers = append(powers, level)
		}
	}

	if len(powers) == 0 {
		return nil, fmt.Errorf("no valid power readings parsed from tinySA response")
	}

	return powers, nil
}
