package store

import (
	"encoding/json"
	"errors"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
)

// ErrNotOrphaned is returned when attempting to prune a clone or workspace whose root directory still exists.
var ErrNotOrphaned = errors.New("scope root directory still exists")

// Orphan describes an orphaned clone or pinned workspace staging folder whose root is missing on disk.
type Orphan struct {
	Scope    string `json:"scope"`
	ID       string `json:"id"`
	RelPath  string `json:"rel_path"`
	Root     string `json:"root"`
	LastSeen string `json:"last_seen,omitempty"`
}

// CheckRootOrphaned returns true only when root is a valid absolute path that is missing or not a directory.
func CheckRootOrphaned(root string) bool {
	trimmed := strings.TrimSpace(root)
	if trimmed == "" || !filepath.IsAbs(trimmed) {
		return false
	}
	info, err := os.Stat(trimmed)
	if err != nil {
		return errors.Is(err, os.ErrNotExist) || errors.Is(err, syscall.ENOTDIR)
	}
	return !info.IsDir()
}

// ListOrphans scans repos/*/clones/*/clone.json and pinned/*/workspace.json for missing root directories.
func ListOrphans(storeRoot string) ([]Orphan, error) {
	out := make([]Orphan, 0)

	absRoot, err := filepath.Abs(storeRoot)
	if err != nil {
		return out, err
	}
	canonRoot, err := filepath.EvalSymlinks(absRoot)
	if err != nil {
		if os.IsNotExist(err) {
			return out, nil
		}
		return nil, err
	}

	// 1. Clones under repos/<repo_id>/clones/<clone_id>/clone.json
	reposDir := filepath.Join(absRoot, "repos")
	if repoEntries, err := os.ReadDir(reposDir); err == nil {
		for _, repoEntry := range sortedDirEntries(repoEntries) {
			if !repoEntry.IsDir() || strings.HasPrefix(repoEntry.Name(), ".") {
				continue
			}
			clonesDir := filepath.Join(reposDir, repoEntry.Name(), "clones")
			cloneEntries, err := os.ReadDir(clonesDir)
			if err != nil {
				continue
			}
			for _, cloneEntry := range sortedDirEntries(cloneEntries) {
				if !cloneEntry.IsDir() || strings.HasPrefix(cloneEntry.Name(), ".") {
					continue
				}
				cloneAbs := filepath.Join(clonesDir, cloneEntry.Name())
				recordAbs := filepath.Join(cloneAbs, "clone.json")
				if !isConfinedRegularFile(canonRoot, cloneAbs, recordAbs) {
					continue
				}
				rec := readScopeRecord(recordAbs)
				if CheckRootOrphaned(rec.Root) {
					out = append(out, Orphan{
						Scope:    "clone",
						ID:       cloneEntry.Name(),
						RelPath:  path.Join("repos", repoEntry.Name(), "clones", cloneEntry.Name()),
						Root:     rec.Root,
						LastSeen: rec.LastSeen,
					})
				}
			}
		}
	}

	// 2. Pinned workspaces under pinned/<slug>/workspace.json
	pinnedDir := filepath.Join(absRoot, "pinned")
	if pinEntries, err := os.ReadDir(pinnedDir); err == nil {
		for _, pinEntry := range sortedDirEntries(pinEntries) {
			if !pinEntry.IsDir() || strings.HasPrefix(pinEntry.Name(), ".") {
				continue
			}
			pinAbs := filepath.Join(pinnedDir, pinEntry.Name())
			recordAbs := filepath.Join(pinAbs, "workspace.json")
			if !isConfinedRegularFile(canonRoot, pinAbs, recordAbs) {
				continue
			}
			rec := readScopeRecord(recordAbs)
			if CheckRootOrphaned(rec.Root) {
				out = append(out, Orphan{
					Scope:    "pinned",
					ID:       pinEntry.Name(),
					RelPath:  path.Join("pinned", pinEntry.Name()),
					Root:     rec.Root,
					LastSeen: rec.LastSeen,
				})
			}
		}
	}

	sort.Slice(out, func(i, j int) bool {
		return out[i].RelPath < out[j].RelPath
	})
	return out, nil
}

// PruneOrphan safely deletes an orphaned clone or pinned staging folder after confirming
// path shape, symlink confinement inside storeRoot, and live missing-root verification.
func PruneOrphan(storeRoot, targetRelPath string) error {
	if targetRelPath == "" || strings.ContainsRune(targetRelPath, 0) || strings.Contains(targetRelPath, "\\") {
		return ErrInvalidPath
	}
	if strings.HasPrefix(targetRelPath, "/") || filepath.IsAbs(targetRelPath) {
		return ErrInvalidPath
	}

	parts := strings.Split(targetRelPath, "/")
	for _, seg := range parts {
		if seg == "" || seg == "." || seg == ".." || strings.HasPrefix(seg, ".") {
			return ErrInvalidPath
		}
	}

	var recordName string
	switch {
	case len(parts) == 4 && parts[0] == "repos" && parts[2] == "clones":
		recordName = "clone.json"
	case len(parts) == 2 && parts[0] == "pinned":
		recordName = "workspace.json"
	default:
		return ErrInvalidPath
	}

	absRoot, err := filepath.Abs(storeRoot)
	if err != nil {
		return ErrInvalidPath
	}
	canonRoot, err := filepath.EvalSymlinks(absRoot)
	if err != nil {
		if os.IsNotExist(err) {
			return ErrNotFound
		}
		return err
	}

	targetAbs := filepath.Join(absRoot, filepath.FromSlash(path.Clean(targetRelPath)))
	info, err := os.Lstat(targetAbs)
	if err != nil {
		if os.IsNotExist(err) {
			return ErrNotFound
		}
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return ErrInvalidPath
	}

	canonTarget, err := filepath.EvalSymlinks(targetAbs)
	if err != nil {
		return ErrInvalidPath
	}
	if !isStrictlyInside(canonRoot, canonTarget) {
		return ErrInvalidPath
	}

	recordAbs := filepath.Join(targetAbs, recordName)
	recLstat, err := os.Lstat(recordAbs)
	if err != nil {
		if os.IsNotExist(err) {
			return ErrInvalidPath
		}
		return err
	}
	if recLstat.Mode()&os.ModeSymlink != 0 || !recLstat.Mode().IsRegular() {
		return ErrInvalidPath
	}

	data, err := os.ReadFile(recordAbs)
	if err != nil {
		return err
	}
	var rec scopeRecord
	if err := json.Unmarshal(data, &rec); err != nil {
		return ErrInvalidPath
	}
	if !filepath.IsAbs(rec.Root) {
		return ErrInvalidPath
	}
	if !CheckRootOrphaned(rec.Root) {
		return ErrNotOrphaned
	}

	return os.RemoveAll(canonTarget)
}

func isConfinedRegularFile(canonRoot, dirAbs, fileAbs string) bool {
	dirInfo, err := os.Lstat(dirAbs)
	if err != nil || dirInfo.Mode()&os.ModeSymlink != 0 || !dirInfo.IsDir() {
		return false
	}
	canonDir, err := filepath.EvalSymlinks(dirAbs)
	if err != nil || !isStrictlyInside(canonRoot, canonDir) {
		return false
	}
	fileInfo, err := os.Lstat(fileAbs)
	if err != nil || fileInfo.Mode()&os.ModeSymlink != 0 || !fileInfo.Mode().IsRegular() {
		return false
	}
	canonFile, err := filepath.EvalSymlinks(fileAbs)
	if err != nil || !isStrictlyInside(canonRoot, canonFile) {
		return false
	}
	return true
}

func isStrictlyInside(canonBase, canonTarget string) bool {
	rel, err := filepath.Rel(canonBase, canonTarget)
	if err != nil {
		return false
	}
	return rel != "." && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator))
}
