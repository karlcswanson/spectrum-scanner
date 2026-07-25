// Package version holds build metadata, injected at build time via -ldflags
// (see the Makefile / .goreleaser.yaml). Defaults apply to `go run` / dev builds.
package version

var (
	// Version is the semver tag (e.g. v1.2.3) or "dev".
	Version = "dev"
	// Commit is the short git SHA.
	Commit = "none"
	// Date is the build timestamp (RFC3339).
	Date = "unknown"
)

// String renders a human-readable version line.
func String() string {
	return Version + " (commit " + Commit + ", built " + Date + ")"
}

// Info is the machine-readable form (served at /api/version).
type Info struct {
	Version string `json:"version"`
	Commit  string `json:"commit"`
	Date    string `json:"date"`
}

// Get returns the current build info.
func Get() Info {
	return Info{Version: Version, Commit: Commit, Date: Date}
}
