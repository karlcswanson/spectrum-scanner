package sweep

import (
	"context"
	"log"
	"sync"
	"time"

	"spectrum-pluto/internal/maia"
	"spectrum-pluto/internal/models"
	"spectrum-pluto/internal/mqtt"
)

const (
	// SegmentOverlap is the fraction of overlap between segments (50%)
	SegmentOverlap = 0.5
	// SettleTime is the wait time after tuning for PLL to settle
	SettleTime = 20 * time.Millisecond
)

// Engine orchestrates frequency sweeping across bands
type Engine struct {
	maia   *maia.Client
	config *models.Config
	mqtt   *mqtt.Client

	mu          sync.RWMutex
	running     bool
	currentBand string
	cancel      context.CancelFunc

	// Subscribers receive scan results via channels
	subscribers   []chan models.ScanLine
	subscribersMu sync.RWMutex
}

// NewEngine creates a new sweep engine
func NewEngine(maiaClient *maia.Client, config *models.Config, mqttClient *mqtt.Client) *Engine {
	return &Engine{
		maia:        maiaClient,
		config:      config,
		mqtt:        mqttClient,
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

// broadcast sends a scan result to all subscribers and MQTT
func (e *Engine) broadcast(scan models.ScanLine, bandName string) {
	e.subscribersMu.RLock()
	defer e.subscribersMu.RUnlock()

	// Send to local WebSocket subscribers
	for _, ch := range e.subscribers {
		select {
		case ch <- scan:
		default:
			// Drop if subscriber is slow (non-blocking)
		}
	}

	// Publish to MQTT if configured
	if e.mqtt != nil && e.mqtt.IsConnected() {
		if err := e.mqtt.PublishScan(scan, bandName); err != nil {
			log.Printf("MQTT publish error: %v", err)
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

// RFInfo contains radio/SDR information from maia
type RFInfo struct {
	SampleRateMHz      float64 `json:"sample_rate_mhz"`
	RxBandwidthMHz     float64 `json:"rx_bandwidth_mhz"`
	BinSizeHz          float64 `json:"bin_size_hz"`
	UsableBandwidthMHz float64 `json:"usable_bandwidth_mhz"`
	RxGainDB           float64 `json:"rx_gain_db"`
	RxGainMode         string  `json:"rx_gain_mode"`
	RxFreqMHz          float64 `json:"rx_freq_mhz"`
	FFTSize            int     `json:"fft_size"`
}

// GetRFInfo fetches current radio settings from maia
func (e *Engine) GetRFInfo() (*RFInfo, error) {
	spec, err := e.maia.GetSpectrometer()
	if err != nil {
		return nil, err
	}
	ad9361, err := e.maia.GetAd9361()
	if err != nil {
		return nil, err
	}

	sampleRate := spec.InputSamplingFrequency
	binSize := sampleRate / float64(maia.FFTSize)
	usableBW := sampleRate * (1 - SegmentOverlap) // 50% usable after cropping

	return &RFInfo{
		SampleRateMHz:      sampleRate / 1e6,
		RxBandwidthMHz:     float64(ad9361.RxRfBandwidth) / 1e6,
		BinSizeHz:          binSize,
		UsableBandwidthMHz: usableBW / 1e6,
		RxGainDB:           ad9361.RxGain,
		RxGainMode:         ad9361.RxGainMode,
		RxFreqMHz:          float64(ad9361.RxLoFrequency) / 1e6,
		FFTSize:            maia.FFTSize,
	}, nil
}

// SetRxBandwidth sets the RF bandwidth on the radio
func (e *Engine) SetRxBandwidth(hz uint32) error {
	log.Printf("Setting RX bandwidth: %.2f MHz", float64(hz)/1e6)
	return e.maia.SetRxBandwidth(hz)
}

// Start begins the sweep loop
func (e *Engine) Start() error {
	e.mu.Lock()
	if e.running {
		e.mu.Unlock()
		return nil
	}

	// Apply gain settings before starting sweep
	gainMode := e.config.RxGainMode
	rxGain := e.config.RxGain
	e.mu.Unlock()

	if gainMode == "" {
		gainMode = "manual"
	}
	if rxGain == 0 {
		rxGain = 40 // default gain
	}

	log.Printf("Setting RX gain: %.1f dB, mode: %s", rxGain, gainMode)
	if err := e.maia.SetGainAndMode(rxGain, gainMode); err != nil {
		log.Printf("Warning: failed to set gain: %v", err)
		// Continue anyway - gain might already be set correctly
	}

	e.mu.Lock()
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

// ApplyGain sets the gain on the radio immediately
func (e *Engine) ApplyGain(gain float64, mode string) error {
	if mode == "" {
		mode = "manual"
	}
	log.Printf("Applying RX gain: %.1f dB, mode: %s", gain, mode)
	return e.maia.SetGainAndMode(gain, mode)
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

			e.broadcast(scan, band.Name)
		}
	}
}

// calculateSegments returns the center frequencies for each segment with overlap
// segmentBandwidth is the actual sample rate (FFT coverage) in Hz
func calculateSegments(band models.Band, segmentBandwidth int64) []int64 {
	var centers []int64

	// Effective hop size accounts for overlap (50% overlap = hop by half segment)
	hopSize := int64(float64(segmentBandwidth) * (1 - SegmentOverlap))

	// Crop amount per edge (25% for 50% overlap)
	cropHz := int64(float64(segmentBandwidth) * SegmentOverlap / 2)

	// Start segment center so that after cropping, usable data begins at band.StartHz
	// First segment center = band.StartHz + halfSegment - cropHz
	// This way: segment spans (center - halfSeg) to (center + halfSeg)
	//           after crop: (center - halfSeg + cropHz) = band.StartHz
	freq := band.StartHz + segmentBandwidth/2 - cropHz

	// Continue until usable portion covers band.StopHz
	// Last usable bin at: center + halfSegment - cropHz >= band.StopHz
	for freq-segmentBandwidth/2+cropHz < band.StopHz {
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
	// Get current settings first - we need sample rate for segment calculation
	spec, err := e.maia.GetSpectrometer()
	if err != nil {
		return models.ScanLine{}, err
	}
	ad9361, err := e.maia.GetAd9361()
	if err != nil {
		return models.ScanLine{}, err
	}

	// Use actual sample rate from spectrometer
	segmentBandwidth := int64(spec.InputSamplingFrequency)
	binHz := spec.InputSamplingFrequency / float64(maia.FFTSize)

	segments := calculateSegments(band, segmentBandwidth)

	log.Printf("  %d segments, %.2f MHz each, %.2f kHz bins",
		len(segments), float64(segmentBandwidth)/1e6, binHz/1e3)

	// Calculate crop amount (25% from each edge for 50% overlap)
	cropBins := int(float64(maia.FFTSize) * SegmentOverlap / 2)

	// Pre-allocate result array based on frequency range
	totalBins := int(float64(band.StopHz-band.StartHz) / binHz)
	allPowers := make([]float64, totalBins)
	for i := range allPowers {
		allPowers[i] = -140 // Initialize to noise floor
	}

	for _, centerFreq := range segments {
		select {
		case <-ctx.Done():
			return models.ScanLine{}, ctx.Err()
		default:
		}

		// Tune to segment center frequency
		if err := e.maia.SetFrequency(uint64(centerFreq)); err != nil {
			return models.ScanLine{}, err
		}

		// Re-apply gain settings after frequency change (maia may reset to AGC)
		e.mu.RLock()
		rxGain := e.config.RxGain
		gainMode := e.config.RxGainMode
		e.mu.RUnlock()
		if gainMode == "" {
			gainMode = "manual"
		}
		if rxGain == 0 {
			rxGain = 40
		}
		if err := e.maia.SetGainAndMode(rxGain, gainMode); err != nil {
			log.Printf("Warning: failed to set gain for segment: %v", err)
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

		// Calculate where this segment's usable data starts in the output array
		// The usable portion starts at centerFreq - segmentBandwidth/2 + cropHz
		// where cropHz = cropBins * binHz
		cropHz := float64(cropBins) * binHz
		usableStartHz := float64(centerFreq) - float64(segmentBandwidth)/2 + cropHz
		startBin := int((usableStartHz - float64(band.StartHz)) / binHz)

		// Copy only the center portion (cropped) to avoid edge artifacts
		for i := cropBins; i < maia.FFTSize-cropBins; i++ {
			outIdx := startBin + (i - cropBins)
			if outIdx >= 0 && outIdx < len(allPowers) {
				// Take maximum (peak hold) when segments overlap
				if powers[i] > allPowers[outIdx] {
					allPowers[outIdx] = powers[i]
				}
			}
		}

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
	firstRead := true

	for time.Now().Before(deadline) {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		default:
		}

		// Set read deadline - longer for first read to allow maia to start streaming
		readTimeout := 100 * time.Millisecond
		if firstRead {
			readTimeout = 500 * time.Millisecond
		}
		conn.SetReadDeadline(time.Now().Add(readTimeout))

		powers, err := maia.ReadFFTFrame(conn)
		if err != nil {
			if firstRead {
				// First read failed - maia may not be ready, log and continue
				log.Printf("Warning: first FFT read timed out, retrying...")
				firstRead = false
				continue
			}
			// Subsequent timeout is expected, just stop collecting
			break
		}
		firstRead = false

		frames = append(frames, powers)
	}

	if len(frames) == 0 {
		log.Printf("Warning: no FFT frames collected")
		return make([]float64, maia.FFTSize), nil
	}

	// If we got multiple frames, skip the first one (may contain stale data)
	// But if we only got one frame, use it
	if len(frames) > 1 {
		frames = frames[1:]
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

	return averaged, nil
}
