package store

import (
	"bufio"
	"encoding/json"
	"errors"
	"io"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"
)

var (
	// ErrInvalidPath is returned when a requested path fails safety or format validation.
	ErrInvalidPath = errors.New("invalid path")
	// ErrNotFound is returned when a requested store file does not exist.
	ErrNotFound = errors.New("file not found")
)

type scopeRecord struct {
	Root     string `json:"root"`
	LastSeen string `json:"last_seen"`
}

// Scan inspects storeRoot and builds the hierarchical navigation tree.
func Scan(storeRoot string) (*Tree, error) {
	tree := &Tree{
		StoreRoot:  storeRoot,
		Repos:      make([]RepoScope, 0),
		Pinned:     make([]PinnedScope, 0),
		Standalone: make([]StandaloneScope, 0),
	}

	info, err := os.Stat(storeRoot)
	if err != nil {
		if os.IsNotExist(err) {
			return tree, nil
		}
		return nil, err
	}
	if !info.IsDir() {
		return tree, nil
	}

	members := pinMembers(storeRoot)
	tree.Repos = scanRepos(storeRoot)
	tree.Pinned = scanPinned(storeRoot, pinGroups(storeRoot, members))
	tree.Standalone = scanStandalone(storeRoot, members)
	return tree, nil
}

// groupMember names the pinned/<slug> group a standalone scope belongs to and its directory relative to the pin.
type groupMember struct {
	Slug  string
	Label string
}

func readPinnedSlugsByRoot(storeRoot string) map[string]string {
	slugByRoot := make(map[string]string)
	entries, err := os.ReadDir(filepath.Join(storeRoot, dirPinned))
	if err != nil {
		return slugByRoot
	}
	for _, entry := range entries {
		if !entry.IsDir() || strings.HasPrefix(entry.Name(), ".") {
			continue
		}
		if rec := readScopeRecord(filepath.Join(storeRoot, dirPinned, entry.Name(), fileWorkspaceJSON)); rec.Root != "" {
			slugByRoot[rec.Root] = entry.Name()
		}
	}
	return slugByRoot
}

// pinMembers maps each grouped standalone scope ID to its group: the pin that is its scope.json root's
// longest pinned.json ancestor (SPEC.md, Identity and routing). Membership is computed, never stored.
func pinMembers(storeRoot string) map[string]groupMember {
	members := make(map[string]groupMember)

	var pins []string
	data, err := os.ReadFile(filepath.Join(storeRoot, filePinnedJSON))
	if err != nil || json.Unmarshal(data, &pins) != nil {
		return members
	}
	slugByRoot := readPinnedSlugsByRoot(storeRoot)

	entries, _ := os.ReadDir(filepath.Join(storeRoot, dirStandalone))
	for _, entry := range entries {
		if !entry.IsDir() || strings.HasPrefix(entry.Name(), ".") {
			continue
		}
		root := readScopeRecord(filepath.Join(storeRoot, dirStandalone, entry.Name(), fileScopeJSON)).Root
		pin, rel := longestPin(pins, root)
		slug, ok := slugByRoot[pin]
		if !ok {
			continue
		}
		label := labelRoot
		if rel != "." {
			label = filepath.ToSlash(rel)
		}
		members[entry.Name()] = groupMember{Slug: slug, Label: label}
	}
	return members
}

// pinGroups builds each pinned/<slug> group's member paths, the pin's own directory first, then by label.
func pinGroups(storeRoot string, members map[string]groupMember) map[string][]PathScope {
	groups := make(map[string][]PathScope)
	for id, m := range members {
		state, active, archive := scanActiveArchive(storeRoot, filepath.Join(storeRoot, dirStandalone, id))
		groups[m.Slug] = append(groups[m.Slug], PathScope{Key: id, Label: m.Label, State: state, Active: active, Archive: archive})
	}
	for _, paths := range groups {
		sort.Slice(paths, func(i, j int) bool {
			a, b := paths[i].Label, paths[j].Label
			if (a == labelRoot) != (b == labelRoot) {
				return a == labelRoot
			}
			return a < b
		})
	}
	return groups
}

// longestPin returns the longest pin containing root by directory component and root's path relative to it.
func longestPin(pins []string, root string) (string, string) {
	best, bestRel := "", ""
	if !filepath.IsAbs(root) {
		return best, bestRel
	}
	for _, pin := range pins {
		if !filepath.IsAbs(pin) || len(pin) <= len(best) {
			continue
		}
		rel, err := filepath.Rel(pin, root)
		if err == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			best, bestRel = pin, rel
		}
	}
	return best, bestRel
}

func scanRepos(storeRoot string) []RepoScope {
	reposDir := filepath.Join(storeRoot, dirRepos)
	entries, err := os.ReadDir(reposDir)
	if err != nil {
		return make([]RepoScope, 0)
	}

	out := make([]RepoScope, 0, len(entries))
	for _, entry := range sortedDirEntries(entries) {
		if !entry.IsDir() || strings.HasPrefix(entry.Name(), ".") {
			continue
		}
		id := entry.Name()
		repoAbs := filepath.Join(reposDir, id)
		scope := RepoScope{
			ID:     id,
			Label:  strings.ReplaceAll(id, "__", "/"),
			Meta:   readRepoMeta(filepath.Join(repoAbs, fileMetaJSON)),
			Wiki:   scanWiki(storeRoot, filepath.Join(repoAbs, dirWiki)),
			Clones: scanClones(storeRoot, repoAbs, filepath.ToSlash(filepath.Join(dirRepos, id))),
		}
		out = append(out, scope)
	}
	return out
}

func scanClones(storeRoot, repoAbs, repoRel string) []CloneScope {
	clonesDir := filepath.Join(repoAbs, dirClones)
	entries, err := os.ReadDir(clonesDir)
	if err != nil {
		return make([]CloneScope, 0)
	}

	out := make([]CloneScope, 0, len(entries))
	for _, entry := range sortedDirEntries(entries) {
		if !entry.IsDir() || strings.HasPrefix(entry.Name(), ".") {
			continue
		}
		id := entry.Name()
		cloneAbs := filepath.Join(clonesDir, id)
		rec := readScopeRecord(filepath.Join(cloneAbs, fileCloneJSON))
		out = append(out, CloneScope{
			ID:       id,
			Label:    id,
			RelPath:  path.Join(repoRel, dirClones, id),
			Root:     rec.Root,
			LastSeen: rec.LastSeen,
			Orphaned: CheckRootOrphaned(rec.Root),
			Paths:    scanPaths(storeRoot, filepath.Join(cloneAbs, dirPaths), keyMain),
		})
	}
	return out
}

func scanPinned(storeRoot string, groups map[string][]PathScope) []PinnedScope {
	pinnedDir := filepath.Join(storeRoot, dirPinned)
	entries, err := os.ReadDir(pinnedDir)
	if err != nil {
		return make([]PinnedScope, 0)
	}

	out := make([]PinnedScope, 0, len(entries))
	for _, entry := range sortedDirEntries(entries) {
		if !entry.IsDir() || strings.HasPrefix(entry.Name(), ".") {
			continue
		}
		id := entry.Name()
		pinAbs := filepath.Join(pinnedDir, id)
		rec := readScopeRecord(filepath.Join(pinAbs, fileWorkspaceJSON))
		out = append(out, PinnedScope{
			ID:       id,
			Label:    id,
			RelPath:  path.Join(dirPinned, id),
			Root:     rec.Root,
			LastSeen: rec.LastSeen,
			Orphaned: CheckRootOrphaned(rec.Root),
			Wiki:     scanWiki(storeRoot, filepath.Join(pinAbs, dirWiki)),
			Paths:    append(scanPaths(storeRoot, filepath.Join(pinAbs, dirPaths), keyRoot), groups[id]...),
		})
	}
	return out
}

func scanStandalone(storeRoot string, members map[string]groupMember) []StandaloneScope {
	standaloneDir := filepath.Join(storeRoot, dirStandalone)
	entries, err := os.ReadDir(standaloneDir)
	if err != nil {
		return make([]StandaloneScope, 0)
	}

	out := make([]StandaloneScope, 0, len(entries))
	for _, entry := range sortedDirEntries(entries) {
		if _, grouped := members[entry.Name()]; grouped || !entry.IsDir() || strings.HasPrefix(entry.Name(), ".") {
			continue
		}
		id := entry.Name()
		dirAbs := filepath.Join(standaloneDir, id)
		state, active, archive := scanActiveArchive(storeRoot, dirAbs)
		out = append(out, StandaloneScope{
			ID:      id,
			Label:   id,
			State:   state,
			Active:  active,
			Archive: archive,
		})
	}
	return out
}

func scanPaths(storeRoot, pathsAbs, primaryKey string) []PathScope {
	entries, err := os.ReadDir(pathsAbs)
	if err != nil {
		return make([]PathScope, 0)
	}

	dirs := make([]os.DirEntry, 0, len(entries))
	for _, entry := range entries {
		if entry.IsDir() && !strings.HasPrefix(entry.Name(), ".") {
			dirs = append(dirs, entry)
		}
	}
	sort.Slice(dirs, func(i, j int) bool {
		a, b := dirs[i].Name(), dirs[j].Name()
		if a == primaryKey && b != primaryKey {
			return true
		}
		if b == primaryKey && a != primaryKey {
			return false
		}
		return a < b
	})

	out := make([]PathScope, 0, len(dirs))
	for _, entry := range dirs {
		key := entry.Name()
		state, active, archive := scanActiveArchive(storeRoot, filepath.Join(pathsAbs, key))
		out = append(out, PathScope{
			Key:     key,
			Label:   formatPathLabel(key),
			State:   state,
			Active:  active,
			Archive: archive,
		})
	}
	return out
}

func formatPathLabel(key string) string {
	switch key {
	case keyMain:
		return "main"
	case keyRoot:
		return labelRoot
	default:
		return strings.ReplaceAll(key, "__", "/")
	}
}

func scanActiveArchive(storeRoot, baseAbs string) (*FileNode, []FileNode, []FileNode) {
	var state *FileNode
	active := make([]FileNode, 0)
	archive := make([]FileNode, 0)

	if entries, err := os.ReadDir(filepath.Join(baseAbs, dirActive)); err == nil {
		for _, entry := range sortedDirEntries(entries) {
			if !isVisibleMarkdownEntry(entry) {
				continue
			}
			node := buildFileNode(storeRoot, filepath.Join(baseAbs, dirActive, entry.Name()))
			if entry.Name() == fileStateCurrent {
				n := node
				state = &n
				continue
			}
			active = append(active, node)
		}
	}

	if entries, err := os.ReadDir(filepath.Join(baseAbs, dirArchive)); err == nil {
		for _, entry := range sortedDirEntries(entries) {
			if !isVisibleMarkdownEntry(entry) {
				continue
			}
			archive = append(archive, buildFileNode(storeRoot, filepath.Join(baseAbs, dirArchive, entry.Name())))
		}
		sort.Slice(archive, func(i, j int) bool {
			return archive[i].Name > archive[j].Name
		})
	}

	return state, active, archive
}

func sortByPriority[T any](items []T, nameOf func(T) string, priority map[string]int) {
	sort.Slice(items, func(i, j int) bool {
		ni, nj := nameOf(items[i]), nameOf(items[j])
		pi, oki := priority[ni]
		pj, okj := priority[nj]
		if oki && okj {
			return pi < pj
		}
		if oki != okj {
			return oki
		}
		return ni < nj
	})
}

func scanWiki(storeRoot, wikiAbs string) *WikiTree {
	info, err := os.Stat(wikiAbs)
	if err != nil || !info.IsDir() {
		return nil
	}
	entries, err := os.ReadDir(wikiAbs)
	if err != nil {
		return nil
	}

	topPriority := map[string]int{"index.md": 0, "log.md": 1, "conventions.md": 2}
	catPriority := map[string]int{"architecture": 0, "decisions": 1, "entities": 2, "troubleshooting": 3}

	topPages := make([]FileNode, 0)
	categories := make([]WikiCategory, 0)

	for _, entry := range sortedDirEntries(entries) {
		name := entry.Name()
		if strings.HasPrefix(name, ".") {
			continue
		}
		if entry.IsDir() {
			if pages := collectWikiCategoryPages(storeRoot, filepath.Join(wikiAbs, name)); len(pages) > 0 {
				categories = append(categories, WikiCategory{Name: name, Pages: pages})
			}
			continue
		}
		if isVisibleMarkdownEntry(entry) {
			topPages = append(topPages, buildFileNode(storeRoot, filepath.Join(wikiAbs, name)))
		}
	}

	sortByPriority(topPages, func(p FileNode) string { return p.Name }, topPriority)
	sortByPriority(categories, func(c WikiCategory) string { return c.Name }, catPriority)

	return &WikiTree{
		TopPages:   topPages,
		Categories: categories,
	}
}

func collectWikiCategoryPages(storeRoot, catAbs string) []FileNode {
	pages := make([]FileNode, 0)
	_ = filepath.WalkDir(catAbs, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if strings.HasPrefix(d.Name(), ".") {
			if d.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if d.IsDir() || !strings.HasSuffix(d.Name(), extMD) {
			return nil
		}
		pages = append(pages, buildFileNode(storeRoot, p))
		return nil
	})
	sort.Slice(pages, func(i, j int) bool {
		return pages[i].Path < pages[j].Path
	})
	return pages
}

func buildFileNode(storeRoot, absPath string) FileNode {
	rel, err := filepath.Rel(storeRoot, absPath)
	if err != nil {
		rel = filepath.Base(absPath)
	}
	relSlash := filepath.ToSlash(rel)
	kind, archived := ClassifyFile(relSlash)
	return FileNode{
		Name:     filepath.Base(absPath),
		Path:     relSlash,
		Title:    ExtractTitle(absPath),
		Kind:     kind,
		Archived: archived,
	}
}

// ClassifyFile returns the fragment/wiki kind and archive status for a store-relative path.
func ClassifyFile(relPath string) (string, bool) {
	norm := path.Clean("/" + strings.ReplaceAll(relPath, "\\", "/"))
	archived := strings.Contains(norm, "/archive/")
	if strings.Contains(norm, "/wiki/") {
		return dirWiki, false
	}

	base := path.Base(norm)
	if len(base) > 9 && base[8] == '-' && isAllDigits(base[:8]) {
		base = base[9:]
	}

	switch {
	case base == fileStateCurrent:
		return "state", archived
	case strings.HasPrefix(base, "decision-"):
		return "decision", archived
	case strings.HasPrefix(base, "log-"):
		return "log", archived
	case strings.HasPrefix(base, "reference-"):
		return "reference", archived
	case strings.HasPrefix(base, "feedback-"):
		return "feedback", archived
	default:
		return "other", archived
	}
}

// ExtractTitle reads the first Markdown `# ` heading from absPath, falling back to the filename.
func ExtractTitle(absPath string) string {
	fallback := strings.TrimSuffix(filepath.Base(absPath), extMD)
	f, err := os.Open(absPath)
	if err != nil {
		return fallback
	}
	defer func() { _ = f.Close() }()

	scanner := bufio.NewScanner(io.LimitReader(f, 4096))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if strings.HasPrefix(line, "# ") {
			title := strings.TrimSpace(strings.TrimPrefix(line, "# "))
			if title != "" {
				return title
			}
		}
	}
	return fallback
}

func cleanRelMarkdownPath(relPath string) (string, error) {
	if relPath == "" || strings.ContainsRune(relPath, 0) {
		return "", ErrInvalidPath
	}
	if strings.HasPrefix(relPath, "/") || strings.Contains(relPath, "\\") || filepath.IsAbs(relPath) {
		return "", ErrInvalidPath
	}
	for _, seg := range strings.Split(relPath, "/") {
		if seg == "" || seg == "." || seg == ".." || strings.HasPrefix(seg, ".") {
			return "", ErrInvalidPath
		}
	}
	clean := path.Clean(relPath)
	if clean == "." || strings.HasPrefix(clean, "..") || !strings.HasSuffix(clean, extMD) {
		return "", ErrInvalidPath
	}
	return clean, nil
}

// ResolveSafeFile validates relPath and returns a canonical path strictly inside storeRoot.
func ResolveSafeFile(storeRoot, relPath string) (string, error) {
	clean, err := cleanRelMarkdownPath(relPath)
	if err != nil {
		return "", err
	}

	absRoot, err := filepath.Abs(storeRoot)
	if err != nil {
		return "", ErrInvalidPath
	}
	canonRoot, err := filepath.EvalSymlinks(absRoot)
	if err != nil {
		if os.IsNotExist(err) {
			return "", ErrNotFound
		}
		return "", err
	}

	candidate := filepath.Join(absRoot, filepath.FromSlash(clean))
	info, err := os.Stat(candidate)
	if err != nil {
		if os.IsNotExist(err) {
			return "", ErrNotFound
		}
		return "", err
	}
	if info.IsDir() {
		return "", ErrInvalidPath
	}

	canonTarget, err := filepath.EvalSymlinks(candidate)
	if err != nil {
		return "", err
	}
	if !isStrictlyInside(canonRoot, canonTarget) {
		return "", ErrInvalidPath
	}
	return canonTarget, nil
}

func readRepoMeta(metaPath string) *RepoMeta {
	data, err := os.ReadFile(metaPath)
	if err != nil {
		return nil
	}
	var m RepoMeta
	if err := json.Unmarshal(data, &m); err != nil {
		return nil
	}
	return &m
}

func readScopeRecord(recordPath string) scopeRecord {
	data, err := os.ReadFile(recordPath)
	if err != nil {
		return scopeRecord{}
	}
	var rec scopeRecord
	if err := json.Unmarshal(data, &rec); err != nil {
		return scopeRecord{}
	}
	return rec
}

func sortedDirEntries(entries []os.DirEntry) []os.DirEntry {
	out := make([]os.DirEntry, len(entries))
	copy(out, entries)
	sort.Slice(out, func(i, j int) bool {
		return out[i].Name() < out[j].Name()
	})
	return out
}

func isVisibleMarkdownEntry(entry os.DirEntry) bool {
	if entry.IsDir() {
		return false
	}
	name := entry.Name()
	return !strings.HasPrefix(name, ".") && strings.HasSuffix(name, extMD)
}

func isAllDigits(s string) bool {
	for i := 0; i < len(s); i++ {
		if s[i] < '0' || s[i] > '9' {
			return false
		}
	}
	return true
}
