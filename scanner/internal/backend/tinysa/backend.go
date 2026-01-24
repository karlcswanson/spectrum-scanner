// Package tinysa provides a scanner backend for the tinySA Ultra spectrum analyzer.
package tinysa

import (
	"context"
	"fmt"
	"log"
	"sync"
	"time"

	"scanner/internal/models"
	"scanner/internal/scanner"
)

const (
	// tinySA Ultra specs
	MinFreqHz           = 100_000       // 100 kHz
	MaxFreqHz           = 5_300_000_000 // 5.3 GHz
	PointsPerSweep      = 450           // Points returned per sweep
	DefaultRBW          = 10_000        // 10 kHz default RBW
	DefaultResolutionHz = 50_000        // 50 kHz default resolution (no chunking needed for most bands)
	MaxChunkSpanHz      = 2_250_000     // 2.25 MHz max per chunk for 5 kHz resolution
)

// Backend implements scanner.Backend for tinySA Ultra
type Backend struct {
	device *Device
	config Config

	mu          sync.Mutex
	connected   bool
	currentBand models.Band
	settings    scanner.SweepSettings
}

// NewBackend creates a new tinySA backend
func NewBackend(cfg Config) *Backend {
	return &Backend{
		config: cfg,
	}
}

// Name returns the device name
func (b *Backend) Name() string {
	return "tinySA Ultra"
}

// Type returns the backend type identifier
func (b *Backend) Type() string {
	return "tinysa"
}

// FrequencyRange returns the supported frequency range
func (b *Backend) FrequencyRange() (minHz, maxHz int64) {
	return MinFreqHz, MaxFreqHz
}

// Connect establishes connection to the tinySA
func (b *Backend) Connect() error {
	b.mu.Lock()
	defer b.mu.Unlock()

	if b.connected {
		return nil
	}

	device, err := Open(b.config)
	if err != nil {
		return fmt.Errorf("failed to connect to tinySA: %w", err)
	}

	b.device = device

	// Switch to input (spectrum analyzer) mode
	if err := b.device.InputOn(); err != nil {
		b.device.Close()
		return fmt.Errorf("failed to set input mode: %w", err)
	}

	// Get version to verify connection
	version, err := b.device.GetVersion()
	if err != nil {
		log.Printf("tinySA: Connected (version query failed)")
	} else {
		log.Printf("tinySA: Connected - %s", version)
	}

	b.connected = true
	return nil
}

// Close disconnects from the tinySA
func (b *Backend) Close() error {
	b.mu.Lock()
	defer b.mu.Unlock()

	if !b.connected {
		return nil
	}

	if b.device != nil {
		b.device.Close()
		b.device = nil
	}

	b.connected = false
	return nil
}

// IsConnected returns connection status
func (b *Backend) IsConnected() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.connected
}

// Configure sets up the tinySA for scanning a specific band
func (b *Backend) Configure(band models.Band, settings scanner.SweepSettings) error {
	b.mu.Lock()
	defer b.mu.Unlock()

	if !b.connected {
		return fmt.Errorf("not connected")
	}

	b.currentBand = band
	b.settings = settings

	// Set RBW if specified (do this first as it affects sweep time)
	rbw := settings.RBW
	if rbw == 0 {
		rbw = DefaultRBW
	}
	// tinySA uses kHz for RBW
	rbwKHz := int(rbw / 1000)
	if rbwKHz > 0 {
		if err := b.device.SetRBW(rbwKHz); err != nil {
			log.Printf("tinySA: Failed to set RBW: %v", err)
		}
	}

	// Set sweep range
	if err := b.device.SetSweepRange(float64(band.StartHz), float64(band.StopHz)); err != nil {
		return fmt.Errorf("failed to set sweep range: %w", err)
	}

	// Resume sweeping and wait for a full sweep to complete
	b.device.Resume()
	time.Sleep(500 * time.Millisecond)

	log.Printf("tinySA: Configured for %s (%.3f - %.3f MHz)",
		band.Name,
		float64(band.StartHz)/1e6,
		float64(band.StopHz)/1e6)

	return nil
}

// Sweep performs a single sweep and returns the data
// For wide bands, this automatically chunks into smaller sweeps for better resolution
func (b *Backend) Sweep(ctx context.Context) (models.ScanLine, error) {
	b.mu.Lock()
	defer b.mu.Unlock()

	if !b.connected {
		return models.ScanLine{}, fmt.Errorf("not connected")
	}

	startHz := float64(b.currentBand.StartHz)
	stopHz := float64(b.currentBand.StopHz)
	bandSpan := stopHz - startHz

	// Determine desired resolution - use RBW/2 as a reasonable target
	// This gives good spectral detail relative to the filter bandwidth
	desiredResHz := float64(b.settings.RBW) / 2
	if desiredResHz < 5000 {
		desiredResHz = 5000 // Minimum 5 kHz resolution
	}
	if desiredResHz > 100000 {
		desiredResHz = 100000 // Maximum 100 kHz resolution
	}

	// Calculate chunk span based on desired resolution
	// Each chunk has PointsPerSweep points, so chunk span = points * resolution
	chunkSpanHz := float64(PointsPerSweep) * desiredResHz

	// Calculate number of chunks needed
	numChunks := int((bandSpan + chunkSpanHz - 1) / chunkSpanHz)
	if numChunks < 1 {
		numChunks = 1
	}

	// Limit chunks to avoid very long sweep times
	if numChunks > 100 {
		numChunks = 100
		chunkSpanHz = bandSpan / float64(numChunks)
	}

	// Collect all power readings
	var allPowers []float64

	for i := 0; i < numChunks; i++ {
		// Check for cancellation
		select {
		case <-ctx.Done():
			return models.ScanLine{}, ctx.Err()
		default:
		}

		// Calculate chunk boundaries
		chunkStart := startHz + float64(i)*chunkSpanHz
		chunkStop := chunkStart + chunkSpanHz
		if chunkStop > stopHz {
			chunkStop = stopHz
		}

		// Set sweep range for this chunk
		if err := b.device.SetSweepRange(chunkStart, chunkStop); err != nil {
			return models.ScanLine{}, fmt.Errorf("failed to set chunk range: %w", err)
		}

		// Resume and wait for sweep
		b.device.Resume()
		time.Sleep(300 * time.Millisecond)

		// Read sweep data
		powers, err := b.device.ReadSweep()
		if err != nil {
			return models.ScanLine{}, fmt.Errorf("chunk %d sweep failed: %w", i, err)
		}

		// For chunks after the first, skip the first point to avoid duplicates
		if i > 0 && len(powers) > 0 {
			powers = powers[1:]
		}

		allPowers = append(allPowers, powers...)

		if numChunks > 1 && i%10 == 0 {
			log.Printf("tinySA: Chunk %d/%d (%.1f - %.1f MHz)",
				i+1, numChunks, chunkStart/1e6, chunkStop/1e6)
		}
	}

	// Calculate actual step size
	step := bandSpan / float64(len(allPowers)-1)

	if numChunks > 1 {
		log.Printf("tinySA: Sweep complete - %d chunks, %d points, %.1f kHz resolution",
			numChunks, len(allPowers), step/1000)
	}

	return models.ScanLine{
		Timestamp: time.Now(),
		HzLo:      startHz,
		HzHi:      stopHz,
		Step:      step,
		Samples:   1,
		Power:     allPowers,
	}, nil
}

// scanRaw reads raw sweep data from the tinySA
func (b *Backend) scanRaw() ([]float64, error) {
	return b.device.ReadSweep()
}

// GetCapabilities returns the capabilities of this backend
func (b *Backend) GetCapabilities() scanner.Capabilities {
	return scanner.Capabilities{
		MinFreqHz:            MinFreqHz,
		MaxFreqHz:            MaxFreqHz,
		RBWOptions:           []int64{3000, 10000, 30000, 100000, 300000, 600000},
		HasTrackingGenerator: true, // tinySA has output mode
		HasAttenuation:       true,
		MinAttenuationDB:     0,
		MaxAttenuationDB:     31,
		HasGainControl:       false,
		TracePoints:          PointsPerSweep,
	}
}

// SetAttenuation sets the input attenuation
func (b *Backend) SetAttenuation(db float64) error {
	b.mu.Lock()
	defer b.mu.Unlock()

	if !b.connected {
		return fmt.Errorf("not connected")
	}

	return b.device.SetAttenuation(int(db))
}
