// Calibration tool for Pluto scanner using tinySA Ultra as signal source
package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/tls"
	"encoding/binary"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"math"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/gorilla/websocket"
	"go.bug.st/serial"
	"gopkg.in/yaml.v3"
)

const (
	FFTSize    = 4096
	SettleTime = 500 * time.Millisecond // Time to wait after changing frequency/level
)

// CalibrationPoint represents a single measurement
type CalibrationPoint struct {
	FrequencyMHz float64 `json:"frequency_mhz" yaml:"frequency_mhz"`
	MeasuredDBm  float64 `json:"measured_dbm" yaml:"measured_dbm"`
}

// Calibration holds the full calibration data
type Calibration struct {
	ReferenceDBm float64            `json:"reference_dbm" yaml:"reference_dbm"`
	RxGain       float64            `json:"rx_gain" yaml:"rx_gain"`
	Timestamp    time.Time          `json:"timestamp" yaml:"timestamp"`
	Points       []CalibrationPoint `json:"points" yaml:"points"`
}

// TinySA controls the tinySA Ultra signal generator
type TinySA struct {
	port   serial.Port
	reader *bufio.Reader
}

// PlutoClient reads from the Pluto via maia-httpd
type PlutoClient struct {
	baseURL    string
	httpClient *http.Client
}

// Ad9361Settings from maia-httpd
type Ad9361Settings struct {
	SamplingFrequency uint32  `json:"sampling_frequency"`
	RxLoFrequency     uint64  `json:"rx_lo_frequency"`
	RxGain            float64 `json:"rx_gain"`
	RxGainMode        string  `json:"rx_gain_mode"`
}

func main() {
	// Command line flags
	tinysaPort := flag.String("tinysa", "/dev/tty.usbmodem4001", "tinySA serial port")
	plutoURL := flag.String("pluto", "https://192.168.2.1", "Pluto maia-httpd URL")
	outputFile := flag.String("output", "calibration.yaml", "Output file for calibration data")
	referenceDBm := flag.Float64("level", -28.0, "Reference level in dBm")
	rxGain := flag.Float64("gain", 40.0, "RX gain to use during calibration")
	startMHz := flag.Float64("start", 470.0, "Start frequency in MHz")
	stopMHz := flag.Float64("stop", 600.0, "Stop frequency in MHz")
	stepMHz := flag.Float64("step", 10.0, "Frequency step in MHz")
	flag.Parse()

	log.Printf("Calibration Tool")
	log.Printf("  tinySA: %s", *tinysaPort)
	log.Printf("  Pluto: %s", *plutoURL)
	log.Printf("  Reference: %.1f dBm", *referenceDBm)
	log.Printf("  RX Gain: %.1f dB", *rxGain)
	log.Printf("  Range: %.1f - %.1f MHz, step %.1f MHz", *startMHz, *stopMHz, *stepMHz)

	// Connect to tinySA
	tinysa, err := NewTinySA(*tinysaPort)
	if err != nil {
		log.Fatalf("Failed to connect to tinySA: %v", err)
	}
	defer tinysa.Close()

	// Connect to Pluto
	pluto := NewPlutoClient(*plutoURL)
	if err := pluto.Connect(); err != nil {
		log.Fatalf("Failed to connect to Pluto: %v", err)
	}

	// Set Pluto gain
	if err := pluto.SetGain(*rxGain); err != nil {
		log.Fatalf("Failed to set Pluto gain: %v", err)
	}
	log.Printf("Pluto gain set to %.1f dB", *rxGain)

	// Enable tinySA output
	if err := tinysa.OutputOn(); err != nil {
		log.Fatalf("Failed to enable tinySA output: %v", err)
	}
	defer tinysa.OutputOff()

	// Set tinySA level
	if err := tinysa.SetLevel(*referenceDBm); err != nil {
		log.Fatalf("Failed to set tinySA level: %v", err)
	}
	log.Printf("tinySA level set to %.1f dBm", *referenceDBm)

	// Collect calibration points
	var points []CalibrationPoint
	for freq := *startMHz; freq <= *stopMHz; freq += *stepMHz {
		log.Printf("Measuring %.1f MHz...", freq)

		// Set tinySA frequency
		if err := tinysa.SetFrequency(freq * 1e6); err != nil {
			log.Printf("  Error setting frequency: %v", err)
			continue
		}

		// Set Pluto to same frequency
		if err := pluto.SetFrequency(uint64(freq * 1e6)); err != nil {
			log.Printf("  Error tuning Pluto: %v", err)
			continue
		}

		// Wait for settle
		time.Sleep(SettleTime)

		// Measure power at this frequency
		power, err := pluto.MeasurePower(freq * 1e6)
		if err != nil {
			log.Printf("  Error measuring: %v", err)
			continue
		}

		log.Printf("  %.1f MHz: measured %.2f dBm (ref %.1f dBm, error %.2f dB)",
			freq, power, *referenceDBm, power-*referenceDBm)

		points = append(points, CalibrationPoint{
			FrequencyMHz: freq,
			MeasuredDBm:  power,
		})
	}

	// Turn off output
	tinysa.OutputOff()

	// Build calibration struct
	cal := Calibration{
		ReferenceDBm: *referenceDBm,
		RxGain:       *rxGain,
		Timestamp:    time.Now(),
		Points:       points,
	}

	// Write to file
	data, err := yaml.Marshal(&cal)
	if err != nil {
		log.Fatalf("Failed to marshal calibration: %v", err)
	}

	if err := os.WriteFile(*outputFile, data, 0644); err != nil {
		log.Fatalf("Failed to write calibration file: %v", err)
	}

	log.Printf("Calibration saved to %s", *outputFile)
	fmt.Println("\nCalibration data:")
	fmt.Println(string(data))
}

// NewTinySA connects to the tinySA Ultra
func NewTinySA(portName string) (*TinySA, error) {
	mode := &serial.Mode{
		BaudRate: 576000, // tinySA Ultra uses 576000 baud
		DataBits: 8,
		Parity:   serial.NoParity,
		StopBits: serial.OneStopBit,
	}

	port, err := serial.Open(portName, mode)
	if err != nil {
		return nil, fmt.Errorf("failed to open serial port: %w", err)
	}

	port.SetReadTimeout(2 * time.Second)

	t := &TinySA{
		port:   port,
		reader: bufio.NewReader(port),
	}

	// Clear any pending data
	t.sendCommand("") // Empty command to sync

	return t, nil
}

func (t *TinySA) Close() {
	t.port.Close()
}

func (t *TinySA) sendCommand(cmd string) error {
	log.Printf("tinySA cmd: %s", cmd)
	_, err := t.port.Write([]byte(cmd + "\r\n"))
	if err != nil {
		return err
	}
	time.Sleep(100 * time.Millisecond) // Give device time to process
	// Read response
	t.port.SetReadTimeout(200 * time.Millisecond)
	buf := make([]byte, 1024)
	n, _ := t.port.Read(buf)
	if n > 0 {
		resp := strings.TrimSpace(string(buf[:n]))
		if resp != "" && resp != cmd {
			log.Printf("tinySA resp: %s", resp)
		}
	}
	return nil
}

func (t *TinySA) OutputOn() error {
	// Switch to output mode (high is default for Ultra)
	t.sendCommand("mode output")
	time.Sleep(500 * time.Millisecond)
	return t.sendCommand("output on")
}

func (t *TinySA) OutputOff() error {
	return t.sendCommand("output off")
}

func (t *TinySA) SetFrequency(hz float64) error {
	// Set start and stop to same frequency for CW output
	t.sendCommand(fmt.Sprintf("sweep start %d", int64(hz)))
	time.Sleep(50 * time.Millisecond)
	t.sendCommand(fmt.Sprintf("sweep stop %d", int64(hz)))
	time.Sleep(50 * time.Millisecond)
	return t.sendCommand("resume")
}

func (t *TinySA) SetLevel(dbm float64) error {
	// Set output level
	cmd := fmt.Sprintf("level %d", int(dbm))
	return t.sendCommand(cmd)
}

// NewPlutoClient creates a new Pluto client
func NewPlutoClient(baseURL string) *PlutoClient {
	tlsConfig := &tls.Config{InsecureSkipVerify: true}
	transport := &http.Transport{TLSClientConfig: tlsConfig}

	return &PlutoClient{
		baseURL: strings.TrimSuffix(baseURL, "/"),
		httpClient: &http.Client{
			Timeout:   10 * time.Second,
			Transport: transport,
		},
	}
}

func (p *PlutoClient) Connect() error {
	_, err := p.getAd9361()
	return err
}

func (p *PlutoClient) getAd9361() (*Ad9361Settings, error) {
	resp, err := p.httpClient.Get(p.baseURL + "/api/ad9361")
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("status %d: %s", resp.StatusCode, body)
	}

	var settings Ad9361Settings
	if err := json.NewDecoder(resp.Body).Decode(&settings); err != nil {
		return nil, err
	}
	return &settings, nil
}

func (p *PlutoClient) SetFrequency(hz uint64) error {
	return p.patch("/api/ad9361", map[string]interface{}{
		"rx_lo_frequency": hz,
	})
}

func (p *PlutoClient) SetGain(db float64) error {
	return p.patch("/api/ad9361", map[string]interface{}{
		"rx_gain":      db,
		"rx_gain_mode": "Manual",
	})
}

func (p *PlutoClient) patch(path string, body map[string]interface{}) error {
	jsonBody, err := json.Marshal(body)
	if err != nil {
		return err
	}

	req, err := http.NewRequest(http.MethodPatch, p.baseURL+path, bytes.NewReader(jsonBody))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := p.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("PATCH %s: status %d: %s", path, resp.StatusCode, body)
	}

	return nil
}

// MeasurePower gets the power reading at a specific frequency
func (p *PlutoClient) MeasurePower(freqHz float64) (float64, error) {
	// Get current settings
	ad9361, err := p.getAd9361()
	if err != nil {
		return 0, err
	}

	// Connect to waterfall websocket
	wsURL := strings.Replace(p.baseURL, "http://", "ws://", 1)
	wsURL = strings.Replace(wsURL, "https://", "wss://", 1)
	wsURL += "/waterfall"

	dialer := websocket.Dialer{
		HandshakeTimeout: 10 * time.Second,
		TLSClientConfig:  &tls.Config{InsecureSkipVerify: true},
	}

	conn, _, err := dialer.DialContext(context.Background(), wsURL, nil)
	if err != nil {
		return 0, fmt.Errorf("websocket connect: %w", err)
	}
	defer conn.Close()

	// Collect a few frames and average
	var powers []float64
	for i := 0; i < 10; i++ {
		conn.SetReadDeadline(time.Now().Add(500 * time.Millisecond))
		_, data, err := conn.ReadMessage()
		if err != nil {
			continue
		}

		if len(data) != FFTSize*4 {
			continue
		}

		// Find the bin for our target frequency
		samplingFreq := float64(ad9361.SamplingFrequency)
		loFreq := float64(ad9361.RxLoFrequency)
		binHz := samplingFreq / float64(FFTSize)

		// Target frequency offset from LO
		offsetHz := freqHz - loFreq
		targetBin := int(offsetHz/binHz) + FFTSize/2

		if targetBin < 0 || targetBin >= FFTSize {
			return 0, fmt.Errorf("frequency %.1f MHz out of range", freqHz/1e6)
		}

		// Read power at target bin (and neighbors for peak detection)
		reader := bytes.NewReader(data)
		fftData := make([]float32, FFTSize)
		binary.Read(reader, binary.LittleEndian, &fftData)

		// Find peak in ±5 bins around target (in LINEAR domain)
		maxLinear := float64(0)
		for b := targetBin - 5; b <= targetBin+5; b++ {
			if b < 0 || b >= FFTSize {
				continue
			}
			val := float64(fftData[b])
			if val > maxLinear {
				maxLinear = val
			}
		}

		if maxLinear > 0 {
			powers = append(powers, maxLinear) // Store LINEAR values
		}
	}

	if len(powers) == 0 {
		return 0, fmt.Errorf("no valid measurements")
	}

	// Average in LINEAR domain
	sum := 0.0
	for _, p := range powers {
		sum += p
	}
	linearAvg := sum / float64(len(powers))

	// Convert to dB and apply calibration offset
	powerDB := 10 * math.Log10(linearAvg)
	powerDB += -ad9361.RxGain - 90.0

	return powerDB, nil
}
