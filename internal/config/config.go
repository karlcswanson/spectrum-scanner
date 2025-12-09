package config

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"

	"github.com/google/uuid"
	"gopkg.in/yaml.v3"

	"spectrum-pluto/internal/models"
)

// DefaultConfig returns sensible defaults for live production RF scanning
func DefaultConfig() *models.Config {
	return &models.Config{
		DeviceID:    uuid.New().String(),
		Name:        "Spectrum Scanner",
		Description: "ADALM-Pluto Scanner",
		DwellTimeMs: 50,
		Mode:        "Average",
		RxGain:      40,       // 40 dB is a good starting point
		RxGainMode:  "manual", // manual gain for consistent sweeps
		Bands: []models.Band{
			{
				Name:    "Business Radio",
				StartHz: 450_000_000,
				StopHz:  470_000_000,
				Enabled: false,
			},
			{
				Name:    "UHF",
				StartHz: 470_000_000,
				StopHz:  608_000_000,
				Enabled: true,
			},
			{
				Name:    "DECT",
				StartHz: 1_920_000_000,
				StopHz:  1_930_000_000,
				Enabled: false,
			},
			{
				Name:    "WiFi 2.4",
				StartHz: 2_400_000_000,
				StopHz:  2_500_000_000,
				Enabled: false,
			},
		},
	}
}

// LoadFromFile loads configuration from a JSON or YAML file
func LoadFromFile(path string) (*models.Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	// Start with defaults
	cfg := DefaultConfig()

	// Determine format by extension
	ext := strings.ToLower(filepath.Ext(path))
	switch ext {
	case ".yaml", ".yml":
		if err := yaml.Unmarshal(data, cfg); err != nil {
			return nil, err
		}
	default:
		if err := json.Unmarshal(data, cfg); err != nil {
			return nil, err
		}
	}

	// Convert MHz to Hz if needed
	cfg.NormalizeBands()

	// Generate device ID if not set
	if cfg.DeviceID == "" {
		cfg.DeviceID = uuid.New().String()
	}

	return cfg, nil
}

// SaveToFile saves configuration to a JSON file
func SaveToFile(path string, cfg *models.Config) error {
	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}

	return os.WriteFile(path, data, 0644)
}

// LoadOrCreate loads config from file if it exists, otherwise creates default
func LoadOrCreate(path string) (*models.Config, error) {
	if _, err := os.Stat(path); os.IsNotExist(err) {
		// File doesn't exist, create default
		cfg := DefaultConfig()
		if err := SaveToFile(path, cfg); err != nil {
			return nil, err
		}
		return cfg, nil
	}

	return LoadFromFile(path)
}
