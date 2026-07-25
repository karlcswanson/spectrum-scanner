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
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/gorilla/websocket"
	"go.bug.st/serial"
	"gopkg.in/yaml.v3"
)

const (
	FFTSize    = 4096
	SettleTime = 500 * time.Millisecond // Time to wait after changing frequency/level

	// LowOutputMaxMHz is the top of the tinySA Ultra's low (sine) output range,
	// which comes from the RF/LOW port. Above this the generator would switch to
	// high (square-wave) output on a different connector, so we only calibrate
	// bands at or below this limit and reject anything higher.
	LowOutputMaxMHz = 800.0
)

// Default calibration settings. These are tuned so that `./calibrate` with no
// flags produces a good calibration on a typical tinySA Ultra + Pluto rig:
//   - level -28 dBm: well above the Pluto noise floor, below front-end compression
//   - gain 30 dB:    linear region of the AD9364 (40+ dB can compress)
//   - pad 0 dB:      assume a direct cable; raise if you add an attenuator
const (
	DefaultLevelDBm = -28.0
	DefaultGainDB   = 30.0
	DefaultPadDB    = 0.0
)

// CalibrationPoint represents a single measurement
type CalibrationPoint struct {
	FrequencyMHz float64 `json:"frequency_mhz" yaml:"frequency_mhz"`
	MeasuredDBm  float64 `json:"measured_dbm" yaml:"measured_dbm"`
}

// Calibration holds the full calibration data
type Calibration struct {
	Serial       string             `json:"serial,omitempty" yaml:"serial,omitempty"`
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

// BandSpec is one frequency range to sweep during calibration.
type BandSpec struct {
	Name     string
	StartMHz float64
	StopMHz  float64
	StepMHz  float64
}

// bandList collects repeatable -band flags.
type bandList []BandSpec

func (b *bandList) String() string {
	parts := make([]string, len(*b))
	for i, s := range *b {
		parts[i] = fmt.Sprintf("%g:%g:%g", s.StartMHz, s.StopMHz, s.StepMHz)
	}
	return strings.Join(parts, " ")
}

// Set parses a "start:stop:step[:name]" band spec (MHz) from a -band flag.
func (b *bandList) Set(v string) error {
	parts := strings.Split(v, ":")
	if len(parts) < 3 || len(parts) > 4 {
		return fmt.Errorf("band %q must be start:stop:step[:name]", v)
	}
	start, err := strconv.ParseFloat(parts[0], 64)
	if err != nil {
		return fmt.Errorf("band %q: bad start: %w", v, err)
	}
	stop, err := strconv.ParseFloat(parts[1], 64)
	if err != nil {
		return fmt.Errorf("band %q: bad stop: %w", v, err)
	}
	step, err := strconv.ParseFloat(parts[2], 64)
	if err != nil {
		return fmt.Errorf("band %q: bad step: %w", v, err)
	}
	if start > stop {
		return fmt.Errorf("band %q: start must be <= stop", v)
	}
	if step <= 0 {
		return fmt.Errorf("band %q: step must be > 0", v)
	}
	name := ""
	if len(parts) == 4 {
		name = parts[3]
	}
	*b = append(*b, BandSpec{Name: name, StartMHz: start, StopMHz: stop, StepMHz: step})
	return nil
}

// defaultBands are the bands the tinySA Ultra can drive cleanly from its low
// (sine) output on the RF/LOW port, i.e. at or below LowOutputMaxMHz. Ranges
// mirror spectrum-ios SpectrumScanner/Models/Models.swift `Band.defaultBands`;
// the step sizes are calibration-specific (sampling density). Higher bands
// (900 MHz ISM, STL, DECT) need the tinySA's high output on a different port and
// are intentionally left out to keep this a single-cable, one-port run.
var defaultBands = bandList{
	{"VHF", 174, 216, 6},
	{"Business Radio", 450, 470, 5},
	{"UHF", 470, 636, 6},
}

func main() {
	// Command line flags
	tinysaPort := flag.String("tinysa", "/dev/tty.usbmodem4001", "tinySA serial port")
	plutoURL := flag.String("pluto", "https://192.168.2.1", "Pluto maia-httpd URL")
	outputFile := flag.String("output", "calibration.yaml", "Output YAML file (paste into config.yaml)")
	jsonFile := flag.String("json", "calibration.json", "Output JSON file (for iOS client handoff)")
	serial := flag.String("serial", "", "Physical unit tag for this run (e.g. Pluto serial). Recommended when comparing multiple units.")
	outDir := flag.String("outdir", "calibrations", "Directory that per-unit output folders are created under (used when -serial is set).")
	level := flag.Float64("level", DefaultLevelDBm, "tinySA output level in dBm (whole numbers; the device truncates fractions)")
	pad := flag.Float64("pad", DefaultPadDB, "Inline attenuator between tinySA and Pluto, in dB. The recorded reference is level-pad.")
	rxGain := flag.Float64("gain", DefaultGainDB, "RX gain to use during calibration")
	var bands bandList
	flag.Var(&bands, "band", "Band to sweep as start:stop:step[:name] in MHz; repeatable. Defaults to the low-output band set when omitted.")
	flag.Parse()

	if len(bands) == 0 {
		bands = defaultBands
	}

	setFlags := map[string]bool{}
	flag.Visit(func(f *flag.Flag) { setFlags[f.Name] = true })

	// When a unit is tagged, isolate its outputs under calibrations/<serial>/ so
	// runs on different units sit side by side for the comparison step (and don't
	// overwrite each other). Only redirect the default filenames — an explicit
	// -output/-json still wins.
	if *serial != "" {
		unitDir := filepath.Join(*outDir, sanitizeSerial(*serial))
		if err := os.MkdirAll(unitDir, 0755); err != nil {
			log.Fatalf("Failed to create output dir %s: %v", unitDir, err)
		}
		if !setFlags["output"] {
			*outputFile = filepath.Join(unitDir, "calibration.yaml")
		}
		if !setFlags["json"] {
			*jsonFile = filepath.Join(unitDir, "calibration.json")
		}
	} else {
		log.Printf("WARNING: no -serial given; outputs won't be unit-tagged. Pass -serial <id> to compare multiple units.")
	}

	// The tinySA drives all of these from its low-output RF/LOW port; bands above
	// the low-output ceiling would need the high-output port and are unsupported.
	for _, band := range bands {
		if band.StopMHz > LowOutputMaxMHz {
			log.Fatalf("band %s stops at %g MHz, above the tinySA low-output limit of %g MHz; "+
				"calibrate it separately from the CAL/HIGH port", bandLabel(band), band.StopMHz, LowOutputMaxMHz)
		}
	}

	// The reference is the power actually arriving at the Pluto: the tinySA is
	// commanded to `level`, and a physical pad drops it by `pad` dB.
	referenceDBm := *level - *pad

	log.Printf("Calibration Tool")
	if *serial != "" {
		log.Printf("  Unit serial: %s", *serial)
	}
	log.Printf("  tinySA: %s", *tinysaPort)
	log.Printf("  Pluto: %s", *plutoURL)
	log.Printf("  Output level: %.1f dBm  (pad %.1f dB -> reference %.1f dBm at Pluto)", *level, *pad, referenceDBm)
	log.Printf("  RX Gain: %.1f dB", *rxGain)
	log.Printf("  Bands: %d", len(bands))
	for _, band := range bands {
		log.Printf("    %-16s %g - %g MHz, step %g MHz", bandLabel(band), band.StartMHz, band.StopMHz, band.StepMHz)
	}

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

	log.Printf(">>> Connect the coax to the tinySA RF/LOW port, then press Enter.")
	waitForEnter()

	// Enable tinySA low output
	if err := tinysa.OutputOn(); err != nil {
		log.Fatalf("Failed to enable tinySA output: %v", err)
	}
	defer tinysa.OutputOff()

	// Set tinySA level (commanded output, before the pad)
	if err := tinysa.SetLevel(*level); err != nil {
		log.Fatalf("Failed to set tinySA level: %v", err)
	}
	log.Printf("tinySA output level set to %.1f dBm", *level)

	// Collect measurements across all bands, keyed by frequency so that points
	// shared between adjacent bands (e.g. 470 MHz at the Business Radio/UHF
	// boundary) get averaged rather than duplicated.
	measured := map[float64][]float64{}
	var order []float64 // frequencies in first-seen order, for dedupe bookkeeping

	for _, band := range bands {
		log.Printf("=== Band %s: %g - %g MHz (step %g) ===", bandLabel(band), band.StartMHz, band.StopMHz, band.StepMHz)

		// Index-based stepping avoids float accumulation drift and guarantees
		// the stop frequency is included.
		steps := int(math.Round((band.StopMHz - band.StartMHz) / band.StepMHz))
		for i := 0; i <= steps; i++ {
			freq := band.StartMHz + float64(i)*band.StepMHz
			if freq > band.StopMHz+1e-9 {
				break
			}
			log.Printf("Measuring %g MHz...", freq)

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

			log.Printf("  %g MHz: measured %.2f dBm (ref %.1f dBm, error %.2f dB)",
				freq, power, referenceDBm, power-referenceDBm)

			if _, seen := measured[freq]; !seen {
				order = append(order, freq)
			}
			measured[freq] = append(measured[freq], power)
		}
	}

	// Turn off output
	tinysa.OutputOff()

	// Collapse duplicate frequencies (average) and sort ascending so the
	// scanner's linear interpolation gets a clean monotonic curve.
	points := make([]CalibrationPoint, 0, len(order))
	for freq, vals := range measured {
		sum := 0.0
		for _, v := range vals {
			sum += v
		}
		points = append(points, CalibrationPoint{
			FrequencyMHz: freq,
			MeasuredDBm:  sum / float64(len(vals)),
		})
	}
	sort.Slice(points, func(i, j int) bool {
		return points[i].FrequencyMHz < points[j].FrequencyMHz
	})

	if len(points) == 0 {
		log.Fatalf("No calibration points collected (check RF connection and devices)")
	}

	// Build calibration struct. Field tags match models.Calibration, so the JSON
	// is byte-compatible with what the server's REST endpoint serves to iOS.
	cal := Calibration{
		Serial:       *serial,
		ReferenceDBm: referenceDBm,
		RxGain:       *rxGain,
		Timestamp:    time.Now(),
		Points:       points,
	}

	// Write YAML (for pasting into config.yaml's calibration: section)
	yamlData, err := yaml.Marshal(&cal)
	if err != nil {
		log.Fatalf("Failed to marshal YAML: %v", err)
	}
	if err := os.WriteFile(*outputFile, yamlData, 0644); err != nil {
		log.Fatalf("Failed to write %s: %v", *outputFile, err)
	}

	// Write JSON (for the iOS client)
	jsonData, err := json.MarshalIndent(&cal, "", "  ")
	if err != nil {
		log.Fatalf("Failed to marshal JSON: %v", err)
	}
	if err := os.WriteFile(*jsonFile, append(jsonData, '\n'), 0644); err != nil {
		log.Fatalf("Failed to write %s: %v", *jsonFile, err)
	}

	log.Printf("Calibration complete: %d points across %d bands", len(points), len(bands))
	log.Printf("  YAML (config.yaml): %s", *outputFile)
	log.Printf("  JSON (iOS):         %s", *jsonFile)
	fmt.Println("\nCalibration data (YAML):")
	fmt.Println(string(yamlData))
}

// sanitizeSerial makes an operator-supplied serial safe to use as a directory
// name (keeps alnum, dash, underscore, dot; collapses everything else to '_').
func sanitizeSerial(s string) string {
	var b strings.Builder
	for _, r := range s {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9', r == '-', r == '_', r == '.':
			b.WriteRune(r)
		default:
			b.WriteRune('_')
		}
	}
	out := b.String()
	if out == "" {
		return "unknown"
	}
	return out
}

// bandLabel returns the band name, or a frequency range if unnamed.
func bandLabel(b BandSpec) string {
	if b.Name != "" {
		return b.Name
	}
	return fmt.Sprintf("%g-%gMHz", b.StartMHz, b.StopMHz)
}

// waitForEnter blocks until the operator presses Enter.
func waitForEnter() {
	bufio.NewScanner(os.Stdin).Scan()
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
	// Low (sine) output from the RF/LOW port. We only calibrate bands the low
	// output can reach (<=800 MHz), so we never touch the high output path.
	t.sendCommand("mode low output")
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
