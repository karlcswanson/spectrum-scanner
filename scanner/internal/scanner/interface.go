// Package scanner defines the common interface for spectrum analyzer backends.
package scanner

import (
	"context"

	"scanner/internal/models"
)

// Backend defines the interface that all spectrum analyzer backends must implement.
// This allows the sweep engine to work with different hardware:
// - ADALM-Pluto (via maia-httpd)
// - OWON HSA1016 (via SCPI over TCP)
// - RTL-SDR (via rtl_power or SoapySDR)
// - RF Explorer (via serial)
// - TTi (via SCPI)
type Backend interface {
	// Identity returns information about this scanner
	Name() string
	Type() string // "pluto", "owon", "rtlsdr", "rfexplorer", "tti"

	// Capabilities returns the frequency range this scanner supports
	FrequencyRange() (minHz, maxHz int64)

	// Connect establishes connection to the hardware
	Connect() error

	// Close cleanly disconnects from the hardware
	Close() error

	// IsConnected returns whether the backend is connected
	IsConnected() bool

	// Configure prepares the scanner for a specific band
	// This sets frequency range, RBW, attenuation, etc.
	Configure(band models.Band, settings SweepSettings) error

	// Sweep performs a single sweep and returns the scan data
	// The backend should handle all hardware-specific details
	Sweep(ctx context.Context) (models.ScanLine, error)
}

// SweepSettings contains settings that apply to the sweep
type SweepSettings struct {
	// RBW is the resolution bandwidth in Hz (0 = auto)
	RBW int64

	// VBW is the video bandwidth in Hz (0 = auto)
	VBW int64

	// Attenuation in dB (for backends that support it)
	AttenuationDB float64

	// DwellTimeMs is how long to dwell on each segment
	DwellTimeMs int

	// Averaging count (1 = no averaging)
	Averaging int

	// RxGain for SDR backends (dB)
	RxGain float64

	// RxGainMode for SDR backends ("manual", "slow_attack", "fast_attack")
	RxGainMode string
}

// Capabilities describes what a backend can do
type Capabilities struct {
	// Frequency range
	MinFreqHz int64
	MaxFreqHz int64

	// RBW options (empty = continuous)
	RBWOptions []int64

	// Whether the backend supports tracking generator
	HasTrackingGenerator bool

	// Whether attenuation is adjustable
	HasAttenuation   bool
	MinAttenuationDB float64
	MaxAttenuationDB float64

	// Whether gain is adjustable (SDR)
	HasGainControl bool
	MinGainDB      float64
	MaxGainDB      float64

	// Number of trace points per sweep
	TracePoints int
}

// BackendInfo contains static information about a backend
type BackendInfo struct {
	Type         string
	Manufacturer string
	Model        string
	Serial       string
	Firmware     string
}

// Calibratable is an optional interface for backends that support calibration
type Calibratable interface {
	SetCalibration(cal *models.Calibration)
	GetCalibration() *models.Calibration
}
