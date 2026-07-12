package config

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"

	"github.com/google/uuid"
	"gopkg.in/yaml.v3"

	"scanner/internal/models"
)

// DefaultConfig returns sensible defaults for live production RF scanning
func DefaultConfig() *models.Config {
	return &models.Config{
		DeviceID:    uuid.New().String(),
		DwellTimeMs: 50,
		Mode:        "Average",
		RxGain:      30,       // 30 dB provides linear response
		RxGainMode:  "manual", // manual gain for consistent sweeps
		AutoStart:   true,     // Start scanning on launch
		// Default bands mirror common/bands.json (the source of truth, from iOS
		// Band.defaultBands). Only UHF is enabled by default. Keep in sync.
		Bands: []models.Band{
			{Name: "VHF", StartHz: 174_000_000, StopHz: 216_000_000, Enabled: false},
			{Name: "Business Radio", StartHz: 450_000_000, StopHz: 470_000_000, Enabled: false},
			{Name: "UHF", StartHz: 470_000_000, StopHz: 636_000_000, Enabled: true},
			{Name: "900 MHz ISM", StartHz: 902_000_000, StopHz: 928_000_000, Enabled: false},
			{Name: "STL", StartHz: 944_000_000, StopHz: 960_000_000, Enabled: false},
			{Name: "DECT", StartHz: 1_920_000_000, StopHz: 1_930_000_000, Enabled: false},
			{Name: "WiFi 2.4", StartHz: 2_400_000_000, StopHz: 2_500_000_000, Enabled: false},
			{Name: "CBRS", StartHz: 3_550_000_000, StopHz: 3_700_000_000, Enabled: false},
			{Name: "WiFi 5", StartHz: 5_150_000_000, StopHz: 5_850_000_000, Enabled: false},
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

// SaveToFile saves configuration to a JSON or YAML file based on extension
func SaveToFile(path string, cfg *models.Config) error {
	ext := strings.ToLower(filepath.Ext(path))

	// Prepare bands for saving (convert Hz to MHz for YAML)
	cfg.PrepareSave()

	var data []byte
	var err error

	switch ext {
	case ".yaml", ".yml":
		data, err = yaml.Marshal(cfg)
	default:
		data, err = json.MarshalIndent(cfg, "", "  ")
	}

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

// AppName is the application name used for config directories
const AppName = "Spectrum Scanner"

// AppConfigDir returns the system config directory for the app
// macOS: ~/Library/Application Support/Spectrum Scanner
// Linux: ~/.config/Spectrum Scanner
// Windows: %AppData%/Spectrum Scanner
func AppConfigDir() string {
	configDir, err := os.UserConfigDir()
	if err != nil {
		return "."
	}
	appDir := filepath.Join(configDir, AppName)
	os.MkdirAll(appDir, 0755)
	return appDir
}

// DiscoverConfigPath finds the config file path using priority:
// 1. Explicit path (if provided)
// 2. ./config.yaml (local directory)
// 3. System config directory
// Returns the path and whether a config file was found
func DiscoverConfigPath(explicit string) (path string, found bool) {
	// Explicit path takes priority
	if explicit != "" {
		if _, err := os.Stat(explicit); err == nil {
			return explicit, true
		}
		return explicit, false
	}

	// Check local directory
	if _, err := os.Stat("config.yaml"); err == nil {
		return "config.yaml", true
	}

	// Check system config directory
	systemPath := filepath.Join(AppConfigDir(), "config.yaml")
	if _, err := os.Stat(systemPath); err == nil {
		return systemPath, true
	}

	// Return system path as default location (for saving new config)
	return systemPath, false
}

// Load discovers and loads configuration
// Priority: explicit path > ./config.yaml > system config > defaults
func Load(explicit string) (*models.Config, string, error) {
	path, found := DiscoverConfigPath(explicit)

	if found {
		cfg, err := LoadFromFile(path)
		if err != nil {
			return nil, path, err
		}
		return cfg, path, nil
	}

	// No config found, use defaults
	return DefaultConfig(), path, nil
}

// Options holds runtime options that can come from flags or env vars
type Options struct {
	ConfigFile  string // Explicit config file path
	ListenAddr  string // HTTP listen address
	BackendType string // Backend type: pluto, owon
	BackendAddr string // Backend address (IP or URL)
}

// DefaultOptions returns options with sensible defaults
func DefaultOptions() Options {
	return Options{
		ListenAddr: ":8080",
	}
}

// ParseEnv reads environment variables into options
func (o *Options) ParseEnv() {
	if v := os.Getenv("SCANNER_CONFIG"); v != "" && o.ConfigFile == "" {
		o.ConfigFile = v
	}
	if v := os.Getenv("SCANNER_LISTEN"); v != "" && o.ListenAddr == "" {
		o.ListenAddr = v
	}
	if v := os.Getenv("SCANNER_BACKEND"); v != "" && o.BackendType == "" {
		o.BackendType = v
	}
	if v := os.Getenv("SCANNER_ADDR"); v != "" && o.BackendAddr == "" {
		o.BackendAddr = v
	}
}

// ApplyToConfig applies option overrides to the config
func (o *Options) ApplyToConfig(cfg *models.Config) {
	if o.BackendType != "" {
		if cfg.Backend == nil {
			cfg.Backend = &models.BackendConfig{}
		}
		cfg.Backend.Type = o.BackendType
	}
	if o.BackendAddr != "" {
		if cfg.Backend == nil {
			cfg.Backend = &models.BackendConfig{}
		}
		// Detect if it's a URL or IP address
		if strings.HasPrefix(o.BackendAddr, "http") {
			cfg.Backend.URL = o.BackendAddr
		} else {
			cfg.Backend.Address = o.BackendAddr
		}
	}
}

// LoadWithOptions loads config and applies runtime options
func LoadWithOptions(opts Options) (*models.Config, string, error) {
	// Apply env vars (flags take precedence, so only fill empty values)
	opts.ParseEnv()

	// Load config file
	cfg, path, err := Load(opts.ConfigFile)
	if err != nil {
		return nil, path, err
	}

	// Apply overrides
	opts.ApplyToConfig(cfg)

	return cfg, path, nil
}
