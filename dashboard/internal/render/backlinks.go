package render

import (
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"

	"github.com/BaankeyBihari/memoir-skill/dashboard/internal/store"
)

// Backlink describes another wiki page that links to the current page via [[wikilink]].
type Backlink struct {
	SourcePath  string `json:"source_path"`
	SourceTitle string `json:"source_title"`
	SourceScope string `json:"source_scope"`
	CrossWiki   bool   `json:"cross_wiki"`
	Kind        string `json:"kind"`
	Snippet     string `json:"snippet,omitempty"`
}

// ComputeBacklinks finds all local and cross-wiki pages that reference targetRelPath.
func ComputeBacklinks(storeRoot, targetRelPath string) ([]Backlink, error) {
	targetClean := path.Clean(targetRelPath)
	if _, _, _, ok := WikiRootForPath(targetClean); !ok {
		return make([]Backlink, 0), nil
	}

	out := make([]Backlink, 0)
	for _, scopeKind := range []string{scopeRepos, scopePinned} {
		out = append(out, collectScopeBacklinks(storeRoot, scopeKind, targetClean)...)
	}

	sort.Slice(out, func(i, j int) bool {
		pi := wikiKindOrder(out[i].Kind)
		pj := wikiKindOrder(out[j].Kind)
		if pi != pj {
			return pi < pj
		}
		return out[i].SourcePath < out[j].SourcePath
	})

	return out, nil
}

func collectWikiDirBacklinks(storeRoot, scopeKind, scopeID, targetClean, wikiDir string) []Backlink {
	info, err := os.Stat(wikiDir)
	if err != nil || !info.IsDir() {
		return nil
	}
	var out []Backlink
	_ = filepath.WalkDir(wikiDir, func(p string, d fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return nil
		}
		if strings.HasPrefix(d.Name(), ".") {
			if d.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if bl, ok := backlinkFromWikiFile(storeRoot, scopeKind, scopeID, targetClean, p, d); ok {
			out = append(out, bl)
		}
		return nil
	})
	return out
}

func collectScopeBacklinks(storeRoot, scopeKind, targetClean string) []Backlink {
	baseDir := filepath.Join(storeRoot, scopeKind)
	entries, err := os.ReadDir(baseDir)
	if err != nil {
		return nil
	}
	var out []Backlink
	for _, entry := range entries {
		if !entry.IsDir() || strings.HasPrefix(entry.Name(), ".") {
			continue
		}
		scopeID := entry.Name()
		wikiDir := filepath.Join(baseDir, scopeID, dirWiki)
		out = append(out, collectWikiDirBacklinks(storeRoot, scopeKind, scopeID, targetClean, wikiDir)...)
	}
	return out
}

func backlinkFromWikiFile(storeRoot, scopeKind, scopeID, targetClean, filePath string, d fs.DirEntry) (Backlink, bool) {
	if d.IsDir() || !strings.HasSuffix(d.Name(), extMD) {
		return Backlink{}, false
	}
	rel, err := filepath.Rel(storeRoot, filePath)
	if err != nil {
		return Backlink{}, false
	}
	srcRel := filepath.ToSlash(rel)
	if srcRel == targetClean {
		return Backlink{}, false
	}
	content, err := os.ReadFile(filePath)
	if err != nil {
		return Backlink{}, false
	}
	for _, link := range ExtractWikilinks(storeRoot, srcRel, string(content)) {
		if link.Broken || link.Resolved != targetClean {
			continue
		}
		return Backlink{
			SourcePath:  srcRel,
			SourceTitle: store.ExtractTitle(filePath),
			SourceScope: formatScopeName(scopeKind, scopeID),
			CrossWiki:   link.CrossWiki,
			Kind:        wikiPageKind(srcRel),
			Snippet:     link.Snippet,
		}, true
	}
	return Backlink{}, false
}

func formatScopeName(scopeKind, scopeID string) string {
	if scopeKind == scopeRepos {
		return strings.ReplaceAll(scopeID, "__", "/")
	}
	return scopeID
}

func wikiPageKind(relPath string) string {
	switch path.Base(relPath) {
	case "index.md":
		return "index"
	case "log.md":
		return "log"
	default:
		return "page"
	}
}

func wikiKindOrder(kind string) int {
	switch kind {
	case "page":
		return 0
	case "index":
		return 1
	case "log":
		return 2
	default:
		return 3
	}
}
