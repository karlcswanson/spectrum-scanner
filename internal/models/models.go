package models

import "time"

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

// ScanLine matches the RTLPowerLine format for frontend compatibility
type ScanLine struct {
	ID        string    `json:"id"`
	Timestamp time.Time `json:"timestamp"`
	HzLo      float64   `json:"hz_lo"`
	HzHi      float64   `json:"hz_hi"`
	Step      float64   `json:"step"`
	Samples   float64   `json:"samples"`
	Power     []float64 `json:"power"`
}

// ScannerStatus reports current scanner state
type ScannerStatus struct {
	ID          string  `json:"id"`
	Name        string  `json:"name"`
	Description string  `json:"description"`
	Online      bool    `json:"online"`
	Scanning    bool    `json:"scanning"`
	CurrentBand *string `json:"current_band,omitempty"`
}

// Config holds scanner configuration
type Config struct {
	DeviceID    string  `json:"device_id" yaml:"device_id"`
	Name        string  `json:"name" yaml:"name"`
	Description string  `json:"description" yaml:"description"`
	Bands       []Band  `json:"bands" yaml:"bands"`
	DwellTimeMs int     `json:"dwell_time_ms" yaml:"dwell_time_ms"`
	Mode        string  `json:"mode" yaml:"mode"`                 // "Average" or "PeakDetect"
	RxGain      float64 `json:"rx_gain" yaml:"rx_gain"`           // RX gain in dB (0-73)
	RxGainMode  string  `json:"rx_gain_mode" yaml:"rx_gain_mode"` // "manual", "slow_attack", "fast_attack"
}

// NormalizeBands converts MHz to Hz for all bands
func (c *Config) NormalizeBands() {
	for i := range c.Bands {
		c.Bands[i].NormalizeHz()
	}
}
