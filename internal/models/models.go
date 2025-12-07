package models

import "time"

// Band defines a frequency range to scan
type Band struct {
	Name    string `json:"name"`
	StartHz int64  `json:"start_hz"`
	StopHz  int64  `json:"stop_hz"`
	Enabled bool   `json:"enabled"`
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
	DeviceID    string `json:"device_id"`
	Name        string `json:"name"`
	Description string `json:"description"`
	Bands       []Band `json:"bands"`
	DwellTimeMs int    `json:"dwell_time_ms"`
	Mode        string `json:"mode"` // "Average" or "PeakDetect"
}