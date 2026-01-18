package db

import (
	"bytes"
	"compress/gzip"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"sync"
	"time"

	_ "github.com/mattn/go-sqlite3"

	"scanner/internal/models"
)

// TimelineEntry represents a scan timestamp for the timeline
type TimelineEntry struct {
	ID        int64     `json:"id"`
	Timestamp time.Time `json:"timestamp"`
	Band      string    `json:"band"`
}

// DecimatedScan is a lightweight scan for scrubber preview
type DecimatedScan struct {
	ID        int64     `json:"id"`
	Timestamp time.Time `json:"timestamp"`
	Band      string    `json:"band"`
	HzLo      float64   `json:"hz_lo"`
	HzHi      float64   `json:"hz_hi"`
	Step      float64   `json:"step"`
	Power     []float64 `json:"power"` // Decimated power array
}

// Store handles SQLite storage for scan history
type Store struct {
	db     *sql.DB
	dbPath string
	mu     sync.RWMutex

	// Prepared statements for performance
	insertStmt   *sql.Stmt
	timelineStmt *sql.Stmt
}

// NewStore creates a new SQLite store
func NewStore(dbPath string) (*Store, error) {
	// Ensure directory exists
	dir := filepath.Dir(dbPath)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create db directory: %w", err)
	}

	db, err := sql.Open("sqlite3", dbPath+"?_journal_mode=WAL&_synchronous=NORMAL")
	if err != nil {
		return nil, fmt.Errorf("failed to open database: %w", err)
	}

	s := &Store{
		db:     db,
		dbPath: dbPath,
	}

	if err := s.migrate(); err != nil {
		db.Close()
		return nil, fmt.Errorf("failed to migrate database: %w", err)
	}

	if err := s.prepareStatements(); err != nil {
		db.Close()
		return nil, fmt.Errorf("failed to prepare statements: %w", err)
	}

	log.Printf("SQLite store initialized: %s", dbPath)
	return s, nil
}

// migrate creates the database schema
func (s *Store) migrate() error {
	schema := `
	CREATE TABLE IF NOT EXISTS scans (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		band TEXT NOT NULL,
		timestamp DATETIME NOT NULL,
		hz_lo REAL NOT NULL,
		hz_hi REAL NOT NULL,
		step REAL NOT NULL,
		power BLOB NOT NULL,
		created_at DATETIME DEFAULT CURRENT_TIMESTAMP
	);

	CREATE INDEX IF NOT EXISTS idx_scans_band_timestamp ON scans(band, timestamp);
	CREATE INDEX IF NOT EXISTS idx_scans_timestamp ON scans(timestamp);
	`

	_, err := s.db.Exec(schema)
	return err
}

// prepareStatements creates prepared statements for frequent operations
func (s *Store) prepareStatements() error {
	var err error

	s.insertStmt, err = s.db.Prepare(`
		INSERT INTO scans (band, timestamp, hz_lo, hz_hi, step, power)
		VALUES (?, ?, ?, ?, ?, ?)
	`)
	if err != nil {
		return fmt.Errorf("failed to prepare insert: %w", err)
	}

	s.timelineStmt, err = s.db.Prepare(`
		SELECT id, timestamp, band
		FROM scans
		WHERE band = ? AND timestamp >= ?
		ORDER BY timestamp ASC
	`)
	if err != nil {
		return fmt.Errorf("failed to prepare timeline: %w", err)
	}

	return nil
}

// compressPower compresses the power array using gzip
func compressPower(power []float64) ([]byte, error) {
	jsonData, err := json.Marshal(power)
	if err != nil {
		return nil, err
	}

	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	if _, err := gz.Write(jsonData); err != nil {
		return nil, err
	}
	if err := gz.Close(); err != nil {
		return nil, err
	}

	return buf.Bytes(), nil
}

// decompressPower decompresses the power array
func decompressPower(data []byte) ([]float64, error) {
	gz, err := gzip.NewReader(bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	defer gz.Close()

	jsonData, err := io.ReadAll(gz)
	if err != nil {
		return nil, err
	}

	var power []float64
	if err := json.Unmarshal(jsonData, &power); err != nil {
		return nil, err
	}

	return power, nil
}

// StoreScan saves a scan to the database
func (s *Store) StoreScan(scan *models.ScanLine) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	// Compress power data
	powerData, err := compressPower(scan.Power)
	if err != nil {
		return fmt.Errorf("failed to compress power: %w", err)
	}

	_, err = s.insertStmt.Exec(
		scan.Band,
		scan.Timestamp,
		scan.HzLo,
		scan.HzHi,
		scan.Step,
		powerData,
	)
	if err != nil {
		return fmt.Errorf("failed to insert scan: %w", err)
	}

	return nil
}

// GetTimeline returns timeline entries for a band within the time range
func (s *Store) GetTimeline(band string, hours int) ([]TimelineEntry, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	since := time.Now().Add(-time.Duration(hours) * time.Hour)

	rows, err := s.timelineStmt.Query(band, since)
	if err != nil {
		return nil, fmt.Errorf("failed to query timeline: %w", err)
	}
	defer rows.Close()

	var entries []TimelineEntry
	for rows.Next() {
		var e TimelineEntry
		if err := rows.Scan(&e.ID, &e.Timestamp, &e.Band); err != nil {
			return nil, fmt.Errorf("failed to scan row: %w", err)
		}
		entries = append(entries, e)
	}

	return entries, nil
}

// GetScanAtTime returns the scan closest to the given time
func (s *Store) GetScanAtTime(band string, t time.Time) (*models.ScanLine, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	// Find the scan closest to the requested time
	row := s.db.QueryRow(`
		SELECT id, band, timestamp, hz_lo, hz_hi, step, power
		FROM scans
		WHERE band = ?
		ORDER BY ABS(strftime('%s', timestamp) - strftime('%s', ?))
		LIMIT 1
	`, band, t)

	var scan models.ScanLine
	var powerData []byte

	err := row.Scan(
		&scan.ID,
		&scan.Band,
		&scan.Timestamp,
		&scan.HzLo,
		&scan.HzHi,
		&scan.Step,
		&powerData,
	)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("failed to query scan: %w", err)
	}

	// Decompress power data
	scan.Power, err = decompressPower(powerData)
	if err != nil {
		return nil, fmt.Errorf("failed to decompress power: %w", err)
	}

	return &scan, nil
}

// GetDecimatedScans returns decimated scans for scrubber preview
// Returns one scan per minute (or closest available) with decimated power
func (s *Store) GetDecimatedScans(band string, hours int) ([]DecimatedScan, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	since := time.Now().Add(-time.Duration(hours) * time.Hour)

	// Get one scan per minute using GROUP BY on minute boundary
	rows, err := s.db.Query(`
		SELECT id, band, timestamp, hz_lo, hz_hi, step, power
		FROM scans
		WHERE band = ? AND timestamp >= ?
		AND id IN (
			SELECT MIN(id)
			FROM scans
			WHERE band = ? AND timestamp >= ?
			GROUP BY strftime('%Y-%m-%d %H:%M', timestamp)
		)
		ORDER BY timestamp ASC
	`, band, since, band, since)
	if err != nil {
		return nil, fmt.Errorf("failed to query decimated scans: %w", err)
	}
	defer rows.Close()

	var scans []DecimatedScan
	for rows.Next() {
		var ds DecimatedScan
		var powerData []byte

		if err := rows.Scan(
			&ds.ID,
			&ds.Band,
			&ds.Timestamp,
			&ds.HzLo,
			&ds.HzHi,
			&ds.Step,
			&powerData,
		); err != nil {
			return nil, fmt.Errorf("failed to scan row: %w", err)
		}

		// Decompress and decimate power data
		fullPower, err := decompressPower(powerData)
		if err != nil {
			log.Printf("Warning: failed to decompress scan %d: %v", ds.ID, err)
			continue
		}

		// Decimate to ~200 points for preview
		ds.Power = decimatePower(fullPower, 200)
		scans = append(scans, ds)
	}

	return scans, nil
}

// decimatePower reduces power array to target size using max pooling
func decimatePower(power []float64, targetPoints int) []float64 {
	if len(power) <= targetPoints {
		return power
	}

	factor := float64(len(power)) / float64(targetPoints)
	result := make([]float64, targetPoints)

	for i := 0; i < targetPoints; i++ {
		start := int(float64(i) * factor)
		end := int(float64(i+1) * factor)
		if end > len(power) {
			end = len(power)
		}

		// Use max value in each bin to preserve peaks
		max := power[start]
		for j := start + 1; j < end; j++ {
			if power[j] > max {
				max = power[j]
			}
		}
		result[i] = max
	}

	return result
}

// Cleanup removes scans older than the retention period
func (s *Store) Cleanup(retentionHours int) (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	cutoff := time.Now().Add(-time.Duration(retentionHours) * time.Hour)

	result, err := s.db.Exec(`DELETE FROM scans WHERE timestamp < ?`, cutoff)
	if err != nil {
		return 0, fmt.Errorf("failed to cleanup: %w", err)
	}

	deleted, _ := result.RowsAffected()
	if deleted > 0 {
		log.Printf("Cleaned up %d old scans (retention: %d hours)", deleted, retentionHours)
		// Vacuum to reclaim space periodically
		s.db.Exec("VACUUM")
	}

	return deleted, nil
}

// GetStats returns database statistics
func (s *Store) GetStats() (map[string]interface{}, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	stats := make(map[string]interface{})

	// Total scan count
	var count int64
	s.db.QueryRow("SELECT COUNT(*) FROM scans").Scan(&count)
	stats["total_scans"] = count

	// Scans per band
	rows, err := s.db.Query(`
		SELECT band, COUNT(*) as count, MIN(timestamp) as oldest, MAX(timestamp) as newest
		FROM scans
		GROUP BY band
	`)
	if err == nil {
		defer rows.Close()
		bands := make(map[string]interface{})
		for rows.Next() {
			var band string
			var cnt int64
			var oldest, newest time.Time
			rows.Scan(&band, &cnt, &oldest, &newest)
			bands[band] = map[string]interface{}{
				"count":  cnt,
				"oldest": oldest,
				"newest": newest,
			}
		}
		stats["bands"] = bands
	}

	// Database file size
	if info, err := os.Stat(s.dbPath); err == nil {
		stats["db_size_bytes"] = info.Size()
		stats["db_size_mb"] = float64(info.Size()) / (1024 * 1024)
	}

	return stats, nil
}

// Close closes the database connection
func (s *Store) Close() error {
	if s.insertStmt != nil {
		s.insertStmt.Close()
	}
	if s.timelineStmt != nil {
		s.timelineStmt.Close()
	}
	return s.db.Close()
}
