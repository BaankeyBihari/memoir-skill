package store

import (
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"unicode/utf8"
)

// SearchResult represents a single document match from the in-memory full-text index.
type SearchResult struct {
	Path       string `json:"path"`
	Name       string `json:"name"`
	Title      string `json:"title"`
	Scope      string `json:"scope"`
	ScopeID    string `json:"scope_id"`
	ScopeLabel string `json:"scope_label"`
	Type       string `json:"type"`
	Archived   bool   `json:"archived,omitempty"`
	Snippet    string `json:"snippet"`
	Score      int    `json:"score"`
}

type indexedDoc struct {
	Path       string
	Name       string
	Title      string
	Scope      string
	ScopeID    string
	ScopeLabel string
	Type       string
	Archived   bool
	Body       string
	titleLower string
	pathLower  string
	bodyLower  string
}

// SearchIndex maintains a thread-safe in-memory full-text index over a Memoir store.
type SearchIndex struct {
	mu        sync.RWMutex
	storeRoot string
	docs      []indexedDoc
}

// NewSearchIndex constructs an empty SearchIndex rooted at storeRoot.
func NewSearchIndex(storeRoot string) *SearchIndex {
	return &SearchIndex{
		storeRoot: storeRoot,
		docs:      make([]indexedDoc, 0),
	}
}

func buildIndexedDoc(
	storeRoot, defaultScope, filePath, name string,
	members map[string]groupMember,
) (indexedDoc, bool) {
	rel, err := filepath.Rel(storeRoot, filePath)
	if err != nil {
		return indexedDoc{}, false
	}
	relSlash := filepath.ToSlash(rel)
	raw, err := os.ReadFile(filePath)
	if err != nil {
		return indexedDoc{}, false
	}

	parts := strings.Split(relSlash, "/")
	scopeID := ""
	if len(parts) >= 2 {
		scopeID = parts[1]
	}
	scope, scopeLabel := defaultScope, scopeID
	if defaultScope == scopeRepo {
		scopeLabel = strings.ReplaceAll(scopeID, "__", "/")
	}
	// A pinned group's member fragments live in standalone/ but search under the group.
	if m, ok := members[scopeID]; ok && defaultScope == dirStandalone {
		scope, scopeID, scopeLabel = dirPinned, m.Slug, m.Slug
	}

	body := string(raw)
	title := extractTitleFromString(body, name)
	kind, archived := ClassifyFile(relSlash)

	return indexedDoc{
		Path:       relSlash,
		Name:       name,
		Title:      title,
		Scope:      scope,
		ScopeID:    scopeID,
		ScopeLabel: scopeLabel,
		Type:       kind,
		Archived:   archived,
		Body:       body,
		titleLower: strings.ToLower(title),
		pathLower:  strings.ToLower(relSlash),
		bodyLower:  strings.ToLower(body),
	}, true
}

func indexScopeDirectory(storeRoot, dir, defaultScope string, members map[string]groupMember) []indexedDoc {
	scopeDir := filepath.Join(storeRoot, dir)
	if _, err := os.Stat(scopeDir); err != nil {
		return nil
	}
	var docs []indexedDoc
	_ = filepath.WalkDir(scopeDir, func(p string, d fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return nil
		}
		name := d.Name()
		if strings.HasPrefix(name, ".") {
			if d.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if d.IsDir() || !strings.HasSuffix(name, extMD) {
			return nil
		}
		if doc, ok := buildIndexedDoc(storeRoot, defaultScope, p, name, members); ok {
			docs = append(docs, doc)
		}
		return nil
	})
	return docs
}

// Rebuild rescans repos/, pinned/, and standalone/ and atomically swaps the indexed corpus.
func (idx *SearchIndex) Rebuild() error {
	info, err := os.Stat(idx.storeRoot)
	if err != nil {
		if os.IsNotExist(err) {
			idx.mu.Lock()
			idx.docs = make([]indexedDoc, 0)
			idx.mu.Unlock()
			return nil
		}
		return err
	}
	if !info.IsDir() {
		return nil
	}

	members := pinMembers(idx.storeRoot)
	next := make([]indexedDoc, 0)
	for _, spec := range []struct {
		dir   string
		scope string
	}{
		{dir: dirRepos, scope: scopeRepo},
		{dir: dirPinned, scope: dirPinned},
		{dir: dirStandalone, scope: dirStandalone},
	} {
		next = append(next, indexScopeDirectory(idx.storeRoot, spec.dir, spec.scope, members)...)
	}

	sort.Slice(next, func(i, j int) bool {
		return next[i].Path < next[j].Path
	})

	idx.mu.Lock()
	idx.docs = next
	idx.mu.Unlock()
	return nil
}

func clampSearchLimit(limit int) int {
	if limit <= 0 {
		return 50
	}
	if limit > 200 {
		return 200
	}
	return limit
}

func scoreSearchDoc(doc indexedDoc, tokens []string) (int, bool) {
	score := 0
	for _, tok := range tokens {
		inTitle := strings.Contains(doc.titleLower, tok)
		inPath := strings.Contains(doc.pathLower, tok)
		inBody := strings.Contains(doc.bodyLower, tok)
		if !inTitle && !inPath && !inBody {
			return 0, false
		}
		if inTitle {
			score += 30
		}
		if inPath {
			score += 15
		}
		if inBody {
			score += 5
		}
	}
	if !doc.Archived {
		score += 8
	}
	if doc.Type == dirWiki || doc.Type == "decision" {
		score += 4
	}
	return score, true
}

// Query filters and ranks indexed documents matching q, scopeFilter, and typeFilter.
func (idx *SearchIndex) Query(q, scopeFilter, typeFilter string, limit int) []SearchResult {
	limit = clampSearchLimit(limit)
	sf := normalizeScopeFilter(scopeFilter)
	tf := normalizeTypeFilter(typeFilter)
	tokens := strings.Fields(strings.ToLower(strings.TrimSpace(q)))

	idx.mu.RLock()
	docs := idx.docs
	idx.mu.RUnlock()

	results := make([]SearchResult, 0)
	for _, doc := range docs {
		if (sf != "" && doc.Scope != sf) || (tf != "" && doc.Type != tf) {
			continue
		}
		score, ok := scoreSearchDoc(doc, tokens)
		if !ok {
			continue
		}
		results = append(results, SearchResult{
			Path:       doc.Path,
			Name:       doc.Name,
			Title:      doc.Title,
			Scope:      doc.Scope,
			ScopeID:    doc.ScopeID,
			ScopeLabel: doc.ScopeLabel,
			Type:       doc.Type,
			Archived:   doc.Archived,
			Snippet:    buildSnippet(doc.Body, tokens),
			Score:      score,
		})
	}

	sort.Slice(results, func(i, j int) bool {
		if results[i].Score != results[j].Score {
			return results[i].Score > results[j].Score
		}
		if results[i].Archived != results[j].Archived {
			return !results[i].Archived
		}
		return results[i].Path < results[j].Path
	})

	if len(results) > limit {
		results = results[:limit]
	}
	return results
}

func normalizeScopeFilter(s string) string {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "", "all":
		return ""
	case scopeRepo, dirRepos:
		return scopeRepo
	case dirPinned:
		return dirPinned
	case dirStandalone:
		return dirStandalone
	default:
		return strings.ToLower(strings.TrimSpace(s))
	}
}

func normalizeTypeFilter(t string) string {
	switch strings.ToLower(strings.TrimSpace(t)) {
	case "", "all":
		return ""
	default:
		return strings.ToLower(strings.TrimSpace(t))
	}
}

func extractTitleFromString(body, filename string) string {
	for _, rawLine := range strings.SplitN(body, "\n", 20) {
		trimmed := strings.TrimSpace(rawLine)
		if strings.HasPrefix(trimmed, "# ") {
			title := strings.TrimSpace(strings.TrimPrefix(trimmed, "# "))
			if title != "" {
				return title
			}
		}
	}
	return strings.TrimSuffix(filename, extMD)
}

func buildSnippet(body string, tokens []string) string {
	flat := strings.Join(strings.Fields(body), " ")
	if flat == "" {
		return ""
	}
	if len(tokens) == 0 {
		return sliceRunes(flat, 0, 140)
	}

	lower := strings.ToLower(flat)
	matchByteIdx := -1
	for _, tok := range tokens {
		if i := strings.Index(lower, tok); i >= 0 {
			matchByteIdx = i
			break
		}
	}
	if matchByteIdx < 0 {
		return sliceRunes(flat, 0, 140)
	}

	matchRuneIdx := utf8.RuneCountInString(flat[:matchByteIdx])
	startRune := matchRuneIdx - 45
	if startRune < 0 {
		startRune = 0
	}
	return sliceRunesWindow(flat, startRune, 140)
}

func sliceRunes(s string, start, length int) string {
	runes := []rune(s)
	if start >= len(runes) {
		return ""
	}
	end := start + length
	if end >= len(runes) {
		return string(runes[start:])
	}
	return string(runes[start:end]) + "..."
}

func sliceRunesWindow(s string, start, length int) string {
	runes := []rune(s)
	if len(runes) == 0 {
		return ""
	}
	if start >= len(runes) {
		start = 0
	}
	end := start + length
	prefix := ""
	if start > 0 {
		prefix = "..."
	}
	suffix := ""
	if end < len(runes) {
		suffix = "..."
	} else {
		end = len(runes)
	}
	return prefix + string(runes[start:end]) + suffix
}
