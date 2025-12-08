package sweep

import (
	"context"
	"log"
	"sync"
	"time"

	"spectrum-pluto/internal/maia"
	"spectrum-pluto/internal/models"
)

const (
	// SegmentBandwidth is the width of each sweep segment (20 MHz)
	SegmentBandwidth int64 = 20_000_000
	// SegmentOverlap is the fraction of overlap between segments (50%)
	SegmentOverlap = 0.5
	// SettleTime is the wait time after tuning for PLL to settle
	SettleTime = 5 * time.Millisecond
)

// Engine orchestrates frequency sweeping across bands
type Engine struct {
	maia   *maia.Client
	config *models.Config

	mu          sync.RWMutex
	running     bool
	currentBand string
	cancel      context.CancelFunc

	// Subscribers receive scan results via channels
	subscribers   []chan models.ScanLine
	subscribersMu sync.RWMutex
}

// NewEngine creates a new sweep engine
func NewEngine(maiaClient *maia.Client, config *models.Config) *Engine {
	return &Engine{
		maia:        maiaClient,
		config:      config,
		subscribers: make([]chan models.ScanLine, 0),
	}
}

// Subscribe registers a channel to receive scan results
func (e *Engine) Subscribe() chan models.ScanLine {
	ch := make(chan models.ScanLine, 10)
	e.subscribersMu.Lock()
	e.subscribers = append(e.subscribers, ch)
	e.subscribersMu.Unlock()
	return ch
}

// Unsubscribe removes a subscriber channel
func (e *Engine) Unsubscribe(ch chan models.ScanLine) {
	e.subscribersMu.Lock()
	defer e.subscribersMu.Unlock()

	for i, sub := range e.subscribers {
		if sub == ch {
			e.subscribers = append(e.subscribers[:i], e.subscribers[i+1:]...)
			close(ch)
			return
		}
	}
}

// broadcast sends a scan result to all subscribers
func (e *Engine) broadcast(scan models.ScanLine) {
	e.subscribersMu.RLock()
	defer e.subscribersMu.RUnlock()

	for _, ch := range e.subscribers {
		select {
		case ch <- scan:
		default:
			// Drop if subscriber is slow (non-blocking)
		}
	}
}

// IsRunning returns whether the engine is currently scanning
func (e *Engine) IsRunning() bool {
	e.mu.RLock()
	defer e.mu.RUnlock()
	return e.running
}

// CurrentBand returns the name of the band currently being scanned
func (e *Engine) CurrentBand() string {
	e.mu.RLock()
	defer e.mu.RUnlock()
	return e.currentBand
}

// Start begins the sweep loop
func (e *Engine) Start() error {
	e.mu.Lock()
	if e.running {
		e.mu.Unlock()
		return nil
	}
	e.running = true

	ctx, cancel := context.WithCancel(context.Background())
	e.cancel = cancel
	e.mu.Unlock()

	go e.runLoop(ctx)
	return nil
}

// Stop halts the sweep loop
func (e *Engine) Stop() {
	e.mu.Lock()
	defer e.mu.Unlock()

	if !e.running {
		return
	}

	e.running = false
	if e.cancel != nil {
		e.cancel()
		e.cancel = nil
	}
}

// UpdateConfig updates the engine configuration
func (e *Engine) UpdateConfig(config *models.Config) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.config = config
}

func (e *Engine) runLoop(ctx context.Context) {
	log.Println("Sweep engine started")
	defer func() {
		log.Println("Sweep engine stopped")
		e.mu.Lock()
		e.currentBand = ""
		e.mu.Unlock()
	}()

	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		e.mu.RLock()
		config := e.config
		e.mu.RUnlock()

		for _, band := range config.Bands {
			select {
			case <-ctx.Done():
				return
			default:
			}

			if !band.Enabled {
				continue
			}

			e.mu.Lock()
			e.currentBand = band.Name
			e.mu.Unlock()

			log.Printf("Sweeping band: %s (%.1f - %.1f MHz)",
				band.Name,
				float64(band.StartHz)/1e6,
				float64(band.StopHz)/1e6)

			scan, err := e.sweepBand(ctx, band)
			if err != nil {
				if ctx.Err() != nil {
					return // Context cancelled
				}
				log.Printf("Error sweeping band %s: %v", band.Name, err)
				continue
			}

			e.broadcast(scan)
		}
	}
}

// calculateSegments returns the center frequencies for each segment with overlap
func calculateSegments(band models.Band) []int64 {
	var centers []int64

	// Effective hop size accounts for overlap (50% overlap = hop by half segment)
	hopSize := int64(float64(SegmentBandwidth) * (1 - SegmentOverlap))

	// Crop amount per edge (25% for 50% overlap)
	cropHz := int64(float64(SegmentBandwidth) * SegmentOverlap / 2)

	// Start segment center so that after cropping, usable data begins at band.StartHz
	// First segment center = band.StartHz + halfSegment - cropHz
	// This way: segment spans (center - halfSeg) to (center + halfSeg)
	//           after crop: (center - halfSeg + cropHz) = band.StartHz
	freq := band.StartHz + SegmentBandwidth/2 - cropHz

	// Continue until usable portion covers band.StopHz
	// Last usable bin at: center + halfSegment - cropHz >= band.StopHz
	for freq-SegmentBandwidth/2+cropHz < band.StopHz {
		centers = append(centers, freq)
		freq += hopSize
	}

	// Handle bands smaller than one segment
	if len(centers) == 0 {
		centers = append(centers, (band.StartHz+band.StopHz)/2)
	}

	return centers
}

func (e *Engine) sweepBand(ctx context.Context, band models.Band) (models.ScanLine, error) {
	segments := calculateSegments(band)

	// Get current settings for calibration
	spec, err := e.maia.GetSpectrometer()
	if err != nil {
		return models.ScanLine{}, err
	}
	ad9361, err := e.maia.GetAd9361()
	if err != nil {
		return models.ScanLine{}, err
	}

	binHz := spec.InputSamplingFrequency / float64(maia.FFTSize)

	// Calculate crop amount (25% from each edge for 50% overlap)
	cropBins := int(float64(maia.FFTSize) * SegmentOverlap / 2)
	usableBins := maia.FFTSize - 2*cropBins

	// Pre-allocate result array based on frequency range
	totalBins := int(float64(band.StopHz-band.StartHz) / binHz)
	allPowers := make([]float64, totalBins)
	for i := range allPowers {
		allPowers[i] = -140 // Initialize to noise floor
	}

	for segIdx, centerFreq := range segments {
		select {
		case <-ctx.Done():
			return models.ScanLine{}, ctx.Err()
		default:
		}

		// Tune to segment center frequency
		if err := e.maia.SetFrequency(uint64(centerFreq)); err != nil {
			return models.ScanLine{}, err
		}

		// Wait for PLL to settle
		time.Sleep(SettleTime)

		// Collect FFT frames for this segment
		powers, err := e.collectSegment(ctx)
		if err != nil {
			return models.ScanLine{}, err
		}

		// Apply Hann window correction and dBm calibration
		// Offset: raw value - RX gain - reference calibration
		// Typical Pluto calibration offset is around -90 to -100
		calibrationOffset := -float64(ad9361.RxGain) - 90.0

		for i, p := range powers {
			powers[i] = p + calibrationOffset
		}

		// Calculate where this segment starts in the output array
		segStartHz := centerFreq - SegmentBandwidth/2
		startBin := int(float64(segStartHz-band.StartHz) / binHz)

		// Copy only the center portion (cropped) to avoid edge artifacts
		for i := cropBins; i < maia.FFTSize-cropBins; i++ {
			outIdx := startBin + i
			if outIdx >= 0 && outIdx < len(allPowers) {
				// Take maximum (peak hold) when segments overlap
				if powers[i] > allPowers[outIdx] {
					allPowers[outIdx] = powers[i]
				}
			}
		}

		log.Printf("Segment %d/%d: %.1f MHz (bins %d-%d)",
			segIdx+1, len(segments), float64(centerFreq)/1e6, startBin, startBin+usableBins)
	}

	return models.ScanLine{
		ID:        e.config.DeviceID,
		Timestamp: time.Now().UTC(),
		HzLo:      float64(band.StartHz),
		HzHi:      float64(band.StopHz),
		Step:      binHz,
		Samples:   float64(len(allPowers)),
		Power:     allPowers,
	}, nil
}

func (e *Engine) collectSegment(ctx context.Context) ([]float64, error) {
	conn, err := e.maia.ConnectWaterfall(ctx)
	if err != nil {
		return nil, err
	}
	defer conn.Close()

	e.mu.RLock()
	dwellMs := e.config.DwellTimeMs
	e.mu.RUnlock()

	if dwellMs <= 0 {
		dwellMs = 50 // default 50ms
	}

	dwellDuration := time.Duration(dwellMs) * time.Millisecond
	deadline := time.Now().Add(dwellDuration)

	var frames [][]float64

	for time.Now().Before(deadline) {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		default:
		}

		// Set read deadline to avoid blocking forever
		conn.SetReadDeadline(time.Now().Add(100 * time.Millisecond))

		powers, err := maia.ReadFFTFrame(conn)
		if err != nil {
			// Timeout is expected, just stop collecting
			break
		}
		frames = append(frames, powers)
	}

	if len(frames) == 0 {
		// Return empty spectrum if no frames collected
		return make([]float64, maia.FFTSize), nil
	}

	// Average all collected frames
	averaged := make([]float64, maia.FFTSize)
	for i := 0; i < maia.FFTSize; i++ {
		sum := 0.0
		for _, frame := range frames {
			sum += frame[i]
		}
		averaged[i] = sum / float64(len(frames))
	}

	log.Printf("Collected %d frames for segment", len(frames))
	return averaged, nil
}
