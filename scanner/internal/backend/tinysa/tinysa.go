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
// Signal Generator (Output) Mode
// =============================================================================

// OutputOn enables signal generator output mode
func (d *Device) OutputOn() error {
	d.sendCommand("mode output")
	time.Sleep(500 * time.Millisecond)
	_, err := d.sendCommand("output on")
	return err
}

// OutputOff disables signal generator output
func (d *Device) OutputOff() error {
	_, err := d.sendCommand("output off")
	return err
}

// SetOutputFrequency sets the signal generator frequency in Hz
func (d *Device) SetOutputFrequency(hz float64) error {
	d.sendCommand(fmt.Sprintf("sweep start %d", int64(hz)))
	time.Sleep(50 * time.Millisecond)
	d.sendCommand(fmt.Sprintf("sweep stop %d", int64(hz)))
	time.Sleep(50 * time.Millisecond)
	_, err := d.sendCommand("resume")
	return err
}

// SetOutputFrequencyMHz sets the signal generator frequency in MHz
func (d *Device) SetOutputFrequencyMHz(mhz float64) error {
	return d.SetOutputFrequency(mhz * 1e6)
}

// SetOutputLevel sets the signal generator level in dBm
// Range: approximately -76 to +13 dBm (varies by frequency)
func (d *Device) SetOutputLevel(dbm float64) error {
	_, err := d.sendCommand(fmt.Sprintf("level %d", int(dbm)))
	return err
}

// SetOutput configures both frequency (Hz) and level (dBm)
func (d *Device) SetOutput(freqHz float64, levelDBm float64) error {
	if err := d.SetOutputFrequency(freqHz); err != nil {
		return err
	}
	return d.SetOutputLevel(levelDBm)
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

// SetSweepRangeMHz sets the sweep range in MHz
func (d *Device) SetSweepRangeMHz(startMHz, stopMHz float64) error {
	return d.SetSweepRange(startMHz*1e6, stopMHz*1e6)
}

// SetRBW sets the resolution bandwidth in kHz
// Valid values: 3, 10, 30, 100, 300, 600 or "auto"
func (d *Device) SetRBW(rbwKHz int) error {
	_, err := d.sendCommand(fmt.Sprintf("rbw %d", rbwKHz))
	return err
}

// SetRBWAuto sets RBW to automatic
func (d *Device) SetRBWAuto() error {
	_, err := d.sendCommand("rbw auto")
	return err
}

// =============================================================================
// General Commands
// =============================================================================

// Pause pauses the current sweep
func (d *Device) Pause() error {
	_, err := d.sendCommand("pause")
	return err
}

// Resume resumes sweeping
func (d *Device) Resume() error {
	_, err := d.sendCommand("resume")
	return err
}

// GetVersion returns the firmware version string
func (d *Device) GetVersion() (string, error) {
	return d.sendCommand("version")
}

// GetInfo returns device information
func (d *Device) GetInfo() (string, error) {
	return d.sendCommand("info")
}

// GetBatteryVoltage returns the battery voltage
func (d *Device) GetBatteryVoltage() (string, error) {
	return d.sendCommand("vbat")
}

// SetAttenuation sets internal attenuation (0-31 dB or auto)
func (d *Device) SetAttenuation(db int) error {
	_, err := d.sendCommand(fmt.Sprintf("attenuate %d", db))
	return err
}

// SetAttenuationAuto sets attenuation to automatic
func (d *Device) SetAttenuationAuto() error {
	_, err := d.sendCommand("attenuate auto")
	return err
}

// SetExternalGain sets external gain/attenuation offset (-100 to +100 dB)
func (d *Device) SetExternalGain(db int) error {
	_, err := d.sendCommand(fmt.Sprintf("ext_gain %d", db))
	return err
}

// =============================================================================
// Modulation (Output Mode)
// =============================================================================

// ModulationType represents available modulation types
type ModulationType string

const (
	ModulationOff    ModulationType = "off"
	ModulationAM1kHz ModulationType = "AM_1kHz"
	ModulationAM10Hz ModulationType = "AM_10Hz"
	ModulationNFM    ModulationType = "NFM"
	ModulationWFM    ModulationType = "WFM"
	ModulationExtern ModulationType = "extern"
)

// SetModulation sets the output modulation type
func (d *Device) SetModulation(mod ModulationType) error {
	_, err := d.sendCommand(fmt.Sprintf("modulation %s", mod))
	return err
}

// =============================================================================
// Marker Commands
// =============================================================================

// SetMarker sets a marker to a specific frequency
func (d *Device) SetMarker(id int, freqHz float64) error {
	_, err := d.sendCommand(fmt.Sprintf("marker %d %d", id, int64(freqHz)))
	return err
}

// SetMarkerPeak sets a marker to the peak signal
func (d *Device) SetMarkerPeak(id int) error {
	_, err := d.sendCommand(fmt.Sprintf("marker %d peak", id))
	return err
}

// MarkerOn enables a marker
func (d *Device) MarkerOn(id int) error {
	_, err := d.sendCommand(fmt.Sprintf("marker %d on", id))
	return err
}

// MarkerOff disables a marker
func (d *Device) MarkerOff(id int) error {
	_, err := d.sendCommand(fmt.Sprintf("marker %d off", id))
	return err
}

// =============================================================================
// Calibration Output
// =============================================================================

// SetCalOutput sets the calibration output frequency
// Valid values: 30, 15, 10, 4, 3, 2, 1 MHz or 0 (off)
func (d *Device) SetCalOutput(mhz int) error {
	if mhz == 0 {
		_, err := d.sendCommand("caloutput off")
		return err
	}
	_, err := d.sendCommand(fmt.Sprintf("caloutput %d", mhz))
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

// ReadSweepData performs a sweep and returns raw binary data
func (d *Device) ReadSweepData() ([]byte, int, error) {
	// Use 'data' command for ASCII output (frequency, level pairs)
	_, err := d.port.Write([]byte("data 0\r\n"))
	if err != nil {
		return nil, 0, err
	}

	time.Sleep(100 * time.Millisecond)
	d.port.SetReadTimeout(2 * time.Second)

	// Read response
	buf := make([]byte, 8192)
	n, err := d.port.Read(buf)
	if err != nil {
		return nil, 0, err
	}

	return buf[:n], n, nil
}

// Frequencies returns the frequency array for the current sweep settings
func (d *Device) Frequencies(startHz, stopHz float64, numPoints int) []float64 {
	freqs := make([]float64, numPoints)
	step := (stopHz - startHz) / float64(numPoints-1)
	for i := 0; i < numPoints; i++ {
		freqs[i] = startHz + float64(i)*step
	}
	return freqs
}
