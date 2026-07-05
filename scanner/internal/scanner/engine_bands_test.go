package scanner

import (
	"path/filepath"
	"testing"

	"scanner/internal/config"
	"scanner/internal/models"
	"scanner/internal/mqtt"
)

func bc(name string, start, stop int64, enabled bool) mqtt.BandConfig {
	return mqtt.BandConfig{Name: name, StartHz: start, StopHz: stop, Enabled: enabled}
}

func TestValidateBands(t *testing.T) {
	tests := []struct {
		name    string
		bands   []mqtt.BandConfig
		minHz   int64
		maxHz   int64
		wantErr bool
	}{
		{"valid single", []mqtt.BandConfig{bc("UHF", 470e6, 636e6, true)}, 0, 0, false},
		{"empty list", nil, 0, 0, true},
		{"empty name", []mqtt.BandConfig{bc("  ", 470e6, 636e6, true)}, 0, 0, true},
		{"duplicate name (case-insensitive)", []mqtt.BandConfig{bc("UHF", 470e6, 500e6, true), bc("uhf", 500e6, 636e6, true)}, 0, 0, true},
		{"start >= stop", []mqtt.BandConfig{bc("X", 500e6, 500e6, true)}, 0, 0, true},
		{"below hardware min", []mqtt.BandConfig{bc("X", 50e6, 100e6, true)}, 70e6, 6e9, true},
		{"above hardware max", []mqtt.BandConfig{bc("X", 5e9, 7e9, true)}, 70e6, 6e9, true},
		{"within hardware range", []mqtt.BandConfig{bc("X", 470e6, 636e6, true)}, 70e6, 6e9, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := validateBands(tt.bands, tt.minHz, tt.maxHz)
			if (err != nil) != tt.wantErr {
				t.Errorf("validateBands() error = %v, wantErr = %v", err, tt.wantErr)
			}
		})
	}
}

func TestHandleBandsReconcile(t *testing.T) {
	cfg := &models.Config{Bands: []models.Band{
		{Name: "A", StartHz: 100e6, StopHz: 200e6, Enabled: true},
		{Name: "B", StartHz: 300e6, StopHz: 400e6, Enabled: true},
	}}
	saved := 0
	e := &Engine{config: cfg}
	e.configSaveFunc = func() error { saved++; return nil }

	// Desired set: edit A (new stop, disabled), drop B, add C.
	err := e.HandleBands([]mqtt.BandConfig{
		bc("A", 100e6, 250e6, false),
		bc("C", 900e6, 928e6, true),
	})
	if err != nil {
		t.Fatalf("HandleBands: %v", err)
	}
	if saved != 1 {
		t.Errorf("configSaveFunc calls = %d, want 1", saved)
	}
	if len(cfg.Bands) != 2 {
		t.Fatalf("bands = %d, want 2 (A updated, B removed, C added)", len(cfg.Bands))
	}
	if cfg.Bands[0].Name != "A" || cfg.Bands[0].StopHz != 250e6 || cfg.Bands[0].Enabled {
		t.Errorf("band A not updated: %+v", cfg.Bands[0])
	}
	if cfg.Bands[1].Name != "C" || cfg.Bands[1].StartHz != 900e6 {
		t.Errorf("band C not added: %+v", cfg.Bands[1])
	}
}

func TestHandleBandsRejectsInvalid(t *testing.T) {
	cfg := &models.Config{Bands: []models.Band{
		{Name: "A", StartHz: 100e6, StopHz: 200e6, Enabled: true},
	}}
	saved := 0
	e := &Engine{config: cfg}
	e.configSaveFunc = func() error { saved++; return nil }

	// Duplicate name -> reject, config untouched, no persist.
	err := e.HandleBands([]mqtt.BandConfig{bc("X", 1e6, 2e6, true), bc("x", 2e6, 3e6, true)})
	if err == nil {
		t.Fatal("expected an error for duplicate band names")
	}
	if saved != 0 {
		t.Errorf("configSaveFunc called %d times on invalid input, want 0", saved)
	}
	if len(cfg.Bands) != 1 || cfg.Bands[0].Name != "A" {
		t.Errorf("config was mutated on invalid input: %+v", cfg.Bands)
	}
}

func TestHandleBandsPersistsAcrossReload(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	cfg := &models.Config{
		Name:  "T",
		Bands: []models.Band{{Name: "UHF", StartHz: 470e6, StopHz: 636e6, Enabled: true}},
	}
	if err := config.SaveToFile(path, cfg); err != nil {
		t.Fatalf("seed config: %v", err)
	}

	e := &Engine{config: cfg}
	e.configSaveFunc = func() error { return config.SaveToFile(path, cfg) }

	// Edit UHF's stop and add DECT (disabled).
	if err := e.HandleBands([]mqtt.BandConfig{
		bc("UHF", 470e6, 608e6, true),
		bc("DECT", 1920e6, 1930e6, false),
	}); err != nil {
		t.Fatalf("HandleBands: %v", err)
	}

	// Reload from disk — the edit survived a restart.
	reloaded, err := config.LoadFromFile(path)
	if err != nil {
		t.Fatalf("reload: %v", err)
	}
	byName := map[string]models.Band{}
	for _, b := range reloaded.Bands {
		byName[b.Name] = b
	}
	if len(byName) != 2 {
		t.Fatalf("reloaded bands = %d, want 2", len(byName))
	}
	if byName["UHF"].StopHz != 608e6 {
		t.Errorf("UHF stop not persisted: got %d, want 608000000", byName["UHF"].StopHz)
	}
	dect, ok := byName["DECT"]
	if !ok {
		t.Fatal("DECT not persisted")
	}
	if dect.Enabled {
		t.Error("DECT should be disabled")
	}
}
