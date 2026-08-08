package models

import (
	"sort"
	"time"
)

// Band defines a frequency range to scan
type Band struct {
	Name     string `json:"name" yaml:"name"`
	StartHz  int64  `json:"start_hz" yaml:"-"`
	StopHz   int64  `json:"stop_hz" yaml:"-"`
	StartMHz int64  `json:"-" yaml:"start_mhz"`
	StopMHz  int64  `json:"-" yaml:"stop_mhz"`
	Enabled  bool   `json:"enabled" yaml:"enabled"`
}

// NormalizeHz converts MHz fields to Hz if needed
func (b *Band) NormalizeHz() {
	if b.StartMHz > 0 && b.StartHz == 0 {
		b.StartHz = b.StartMHz * 1_000_000
	}
	if b.StopMHz > 0 && b.StopHz == 0 {
		b.StopHz = b.StopMHz * 1_000_000
	}
}

// PrepareSave converts Hz fields to MHz for YAML serialization
func (b *Band) PrepareSave() {
	if b.StartHz > 0 {
		b.StartMHz = b.StartHz / 1_000_000
	}
	if b.StopHz > 0 {
		b.StopMHz = b.StopHz / 1_000_000
	}
}

// ScanLine matches the RTLPowerLine format for frontend compatibility
type ScanLine struct {
	ID        string    `json:"id"`
	Timestamp time.Time `json:"timestamp"`
	Band      string    `json:"band,omitempty"` // Band name (set before broadcast)
	HzLo      float64   `json:"hz_lo"`
	HzHi      float64   `json:"hz_hi"`
	Step      float64   `json:"step"`
	Samples   float64   `json:"samples"`
	Power     []float64 `json:"power"`
}

// ScannerStatus reports current scanner state
type ScannerStatus struct {
	ID          string  `json:"id"`
	Name        string  `json:"name"` // standalone display label (the device ID; identity is server-side)
	Online      bool    `json:"online"`
	Scanning    bool    `json:"scanning"`
	CurrentBand *string `json:"current_band,omitempty"`
}

// MQTTConfig holds optional MQTT publishing settings
// MQTTConfig is pure transport/connection config. Scanner identity
// (name/location/description) lives at the top level of Config, not here.
type MQTTConfig struct {
	Enabled     bool   `json:"enabled" yaml:"enabled"`
	Broker      string `json:"broker" yaml:"broker"`             // tcp:// | ssl:// | ws:// | wss:// (e.g. "wss://host/mqtt")
	ID          string `json:"id" yaml:"id"`                     // Scanner UUID (from Django admin)
	Token       string `json:"token" yaml:"token"`               // Auth token (from Django admin)
	TopicPrefix string `json:"topic_prefix" yaml:"topic_prefix"` // defaults to "spectrum"

	// TLS options, used only for TLS-based broker schemes (wss/ssl/tls/mqtts).
	// A valid public cert (Let's Encrypt via Caddy) needs neither. For a private
	// CA (event appliance) set CAFile; TLSInsecure skips verification entirely
	// (trusted LAN / self-signed only).
	TLSInsecure bool   `json:"tls_insecure,omitempty" yaml:"tls_insecure,omitempty"`
	CAFile      string `json:"ca_file,omitempty" yaml:"ca_file,omitempty"`
}

// WebConfig holds optional local web server settings
type WebConfig struct {
	Enabled bool   `json:"enabled" yaml:"enabled"`
	Port    int    `json:"port" yaml:"port"` // defaults to 8080
	Host    string `json:"host" yaml:"host"` // defaults to "" (all interfaces)
}

// CalibrationPoint represents a single frequency/power measurement from calibration
type CalibrationPoint struct {
	FrequencyMHz float64 `json:"frequency_mhz" yaml:"frequency_mhz"`
	MeasuredDBm  float64 `json:"measured_dbm" yaml:"measured_dbm"`
}

// Calibration holds calibration data for the scanner
type Calibration struct {
	// Serial identifies the physical unit this calibration was measured on
	// (operator-supplied; provenance for comparing units and picking a default).
	Serial string `json:"serial,omitempty" yaml:"serial,omitempty"`

	// ReferenceDBm is the known power level of the calibration source
	ReferenceDBm float64 `json:"reference_dbm" yaml:"reference_dbm"`

	// Points are the measured values at different frequencies during calibration
	Points []CalibrationPoint `json:"points" yaml:"points"`

	// Timestamp when calibration was performed
	Timestamp time.Time `json:"timestamp,omitempty" yaml:"timestamp,omitempty"`

	// RxGain that was used during calibration (for reference)
	RxGain float64 `json:"rx_gain" yaml:"rx_gain"`
}

// CorrectionAt returns the correction factor (in dB) for a given frequency in Hz.
// The correction should be ADDED to measured values to get calibrated values.
// Uses linear interpolation between calibration points.
func (c *Calibration) CorrectionAt(freqHz float64) float64 {
	if c == nil || len(c.Points) == 0 {
		return 0
	}

	freqMHz := freqHz / 1_000_000

	// Sort points by frequency
	points := make([]CalibrationPoint, len(c.Points))
	copy(points, c.Points)
	sort.Slice(points, func(i, j int) bool {
		return points[i].FrequencyMHz < points[j].FrequencyMHz
	})

	// Calculate correction for each point: reference - measured
	// If reference is -28 dBm and we measured -31, correction is +3 dB
	corrections := make([]float64, len(points))
	for i, p := range points {
		corrections[i] = c.ReferenceDBm - p.MeasuredDBm
	}

	// Below first point: use first correction
	if freqMHz <= points[0].FrequencyMHz {
		return corrections[0]
	}

	// Above last point: use last correction
	if freqMHz >= points[len(points)-1].FrequencyMHz {
		return corrections[len(points)-1]
	}

	// Find surrounding points and interpolate
	for i := 0; i < len(points)-1; i++ {
		if freqMHz >= points[i].FrequencyMHz && freqMHz <= points[i+1].FrequencyMHz {
			// Linear interpolation
			t := (freqMHz - points[i].FrequencyMHz) / (points[i+1].FrequencyMHz - points[i].FrequencyMHz)
			return corrections[i] + t*(corrections[i+1]-corrections[i])
		}
	}

	return 0
}

// IsValid returns true if calibration data exists and is usable
func (c *Calibration) IsValid() bool {
	return c != nil && len(c.Points) > 0
}

// BackendConfig holds configuration for the scanner backend/hardware
type BackendConfig struct {
	// Type specifies which backend to use: "pluto", "owon", "rtlsdr", "rfexplorer", "tti"
	Type string `json:"type" yaml:"type"`

	// Address for network-connected devices (IP or hostname)
	Address string `json:"address" yaml:"address"`

	// Port for network-connected devices (0 = use default)
	Port int `json:"port" yaml:"port"`

	// Device for serial/USB devices (e.g., "/dev/ttyUSB0", "COM3")
	Device string `json:"device" yaml:"device"`

	// URL for HTTP-based backends like maia-httpd (e.g., "https://192.168.2.1")
	URL string `json:"url" yaml:"url"`

	// RBW (Resolution Bandwidth) in Hz, 0 = auto
	RBW int64 `json:"rbw" yaml:"rbw"`

	// VBW (Video Bandwidth) in Hz, 0 = auto
	VBW int64 `json:"vbw" yaml:"vbw"`

	// Attenuation in dB (for backends that support it)
	AttenuationDB float64 `json:"attenuation_db" yaml:"attenuation_db"`
}

// Config holds scanner configuration
type Config struct {
	// AssetTag is an optional device-reported label (barcode / asset tag). Sent
	// to the server when set. Identity is the server-assigned MQTT id (see
	// MQTTConfig.ID); name/location/description live server-side, not here.
	AssetTag    string         `json:"asset_tag,omitempty" yaml:"asset_tag,omitempty"`
	Bands       []Band         `json:"bands" yaml:"bands"`
	DwellTimeMs int            `json:"dwell_time_ms" yaml:"dwell_time_ms"`
	Mode        string         `json:"mode" yaml:"mode"`                           // "Average" or "PeakDetect"
	RxGain      float64        `json:"rx_gain" yaml:"rx_gain"`                     // RX gain in dB (0-73) for SDR
	RxGainMode  string         `json:"rx_gain_mode" yaml:"rx_gain_mode"`           // "manual", "slow_attack", "fast_attack"
	AutoStart   bool           `json:"auto_start" yaml:"auto_start"`               // Start scanning automatically on boot
	Backend     *BackendConfig `json:"backend,omitempty" yaml:"backend,omitempty"` // Hardware backend configuration
	MQTT        *MQTTConfig    `json:"mqtt,omitempty" yaml:"mqtt,omitempty"`       // Optional MQTT publishing
	Web         *WebConfig     `json:"web,omitempty" yaml:"web,omitempty"`         // Optional local web server
	Calibration *Calibration   `json:"calibration,omitempty" yaml:"calibration,omitempty"`
}

// NormalizeBands converts MHz to Hz for all bands
func (c *Config) NormalizeBands() {
	for i := range c.Bands {
		c.Bands[i].NormalizeHz()
	}
}

// PrepareSave converts Hz to MHz for all bands (for YAML serialization)
func (c *Config) PrepareSave() {
	for i := range c.Bands {
		c.Bands[i].PrepareSave()
	}
}
