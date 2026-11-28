package render

import (
	"os"
	"path"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/BaankeyBihari/memoir-skill/dashboard/internal/store"
)

const (
	scopeRepos      = "repos"
	scopePinned     = "pinned"
	dirActive       = "active"
	dirArchive      = "archive"
	dirWiki         = "wiki"
	extMD           = ".md"
	hdrDate         = "Date"
	hdrTarget       = "Target"
	hdrSupersedes   = "Supersedes"
	hdrSupersededBy = "Superseded-By"
	hdrSources      = "Sources"
	typeEntity      = "entity"
)

// MetadataBadge represents a structured header field parsed from a fragment or wiki page.
type MetadataBadge struct {
	Key        string `json:"key"`
	Value      string `json:"value"`
	TargetPath string `json:"target_path,omitempty"`
	URL        string `json:"url,omitempty"`
}

// SourceLink represents a reference listed on a wiki page's Sources: header line.
type SourceLink struct {
	Label      string `json:"label"`
	TargetPath string `json:"target_path,omitempty"`
	Broken     bool   `json:"broken,omitempty"`
}

var (
	decisionFileRe = regexp.MustCompile(`decision-[a-z0-9]+(?:-[a-z0-9]+)*\.md`)
	inlineWikiRe   = regexp.MustCompile(`^\[\[([^\[\]|#]+)(?:#[^\[\]|]+)?(?:\|([^\[\]]+))?\]\]$`)
)

var badgeHeaderKeys = map[string]bool{
	hdrDate:         true,
	"Updated":       true,
	"Type":          true,
	"Status":        true,
	hdrTarget:       true,
	hdrSupersedes:   true,
	hdrSupersededBy: true,
	hdrSources:      true,
}

var bodyFieldKeys = map[string]bool{
	"Decision":     true,
	"Why":          true,
	"Alternatives": true,
	"Deferred":     true,
	"Event":        true,
	"Impact":       true,
	"Feedback":     true,
}

type parsedDoc struct {
	Title        string
	Badges       []MetadataBadge
	Sources      []SourceLink
	BodyMarkdown string
}

func parseLeadingTitle(lines []string, relPath string) (string, int) {
	idx := 0
	for idx < len(lines) && strings.TrimSpace(lines[idx]) == "" {
		idx++
	}
	title := ""
	if idx < len(lines) && strings.HasPrefix(strings.TrimSpace(lines[idx]), "# ") {
		title = strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(lines[idx]), "# "))
		idx++
	}
	if title == "" {
		title = strings.TrimSuffix(path.Base(relPath), extMD)
	}
	return title, idx
}

func scanHeaderBlock(lines []string, startIdx int) (map[string]string, []string, []string, int) {
	rawFields := make(map[string]string)
	var fieldOrder []string
	var bodyFieldLines []string

	idx := startIdx
	for idx < len(lines) {
		trimmed := strings.TrimSpace(lines[idx])
		if trimmed == "" {
			idx++
			break
		}
		key, val, ok := splitHeaderLine(trimmed)
		if !ok {
			break
		}
		if badgeHeaderKeys[key] {
			if _, exists := rawFields[key]; !exists {
				fieldOrder = append(fieldOrder, key)
			}
			rawFields[key] = val
			idx++
			continue
		}
		if bodyFieldKeys[key] {
			bodyFieldLines = append(bodyFieldLines, "**"+key+":** "+val)
			idx++
			continue
		}
		break
	}
	return rawFields, fieldOrder, bodyFieldLines, idx
}

func consumeEntityTargetLine(lines []string, startIdx int, rawFields map[string]string, fieldOrder []string) ([]string, int) {
	if _, hasTarget := rawFields[hdrTarget]; hasTarget || rawFields["Type"] != typeEntity {
		return fieldOrder, startIdx
	}
	// Wiki entity pages place `Target:` right after a blank line below `Sources:`.
	peek := startIdx
	for peek < len(lines) && strings.TrimSpace(lines[peek]) == "" {
		peek++
	}
	if peek < len(lines) {
		if key, val, ok := splitHeaderLine(strings.TrimSpace(lines[peek])); ok && key == hdrTarget {
			rawFields[hdrTarget] = val
			return append(fieldOrder, hdrTarget), peek + 1
		}
	}
	return fieldOrder, startIdx
}

func buildBadgesAndSources(storeRoot, relPath string, fieldOrder []string, rawFields map[string]string) ([]MetadataBadge, []SourceLink) {
	badges := make([]MetadataBadge, 0, len(fieldOrder))
	sources := make([]SourceLink, 0)

	for _, key := range fieldOrder {
		val := rawFields[key]
		if key == hdrSources {
			sources = resolveSources(storeRoot, relPath, val)
			continue
		}
		badge := MetadataBadge{
			Key:   key,
			Value: val,
		}
		switch key {
		case hdrTarget:
			if strings.HasPrefix(val, "http://") || strings.HasPrefix(val, "https://") {
				badge.URL = val
			}
		case hdrSupersedes, hdrSupersededBy:
			badge.TargetPath = resolveDecisionHeaderRef(storeRoot, relPath, val)
		}
		badges = append(badges, badge)
	}
	return badges, sources
}

func parseHeaderAndBody(storeRoot, relPath, raw string) parsedDoc {
	norm := strings.ReplaceAll(raw, "\r\n", "\n")
	lines := strings.Split(norm, "\n")

	title, idx := parseLeadingTitle(lines, relPath)
	rawFields, fieldOrder, bodyFieldLines, idx := scanHeaderBlock(lines, idx)
	fieldOrder, idx = consumeEntityTargetLine(lines, idx, rawFields, fieldOrder)
	badges, sources := buildBadgesAndSources(storeRoot, relPath, fieldOrder, rawFields)

	var bodyParts []string
	if len(bodyFieldLines) > 0 {
		bodyParts = append(bodyParts, strings.Join(bodyFieldLines, "\n\n"))
	}
	if idx < len(lines) {
		rest := strings.TrimLeft(strings.Join(lines[idx:], "\n"), "\n")
		if rest != "" {
			bodyParts = append(bodyParts, rest)
		}
	}

	return parsedDoc{
		Title:        title,
		Badges:       badges,
		Sources:      sources,
		BodyMarkdown: strings.Join(bodyParts, "\n\n"),
	}
}

func splitHeaderLine(line string) (string, string, bool) {
	if strings.HasPrefix(line, "#") || strings.HasPrefix(line, "-") || strings.HasPrefix(line, "*") || strings.HasPrefix(line, ">") || strings.HasPrefix(line, "`") {
		return "", "", false
	}
	colon := strings.IndexByte(line, ':')
	if colon <= 0 {
		return "", "", false
	}
	key := strings.TrimSpace(line[:colon])
	if !badgeHeaderKeys[key] && !bodyFieldKeys[key] {
		return "", "", false
	}
	val := strings.TrimSpace(line[colon+1:])
	return key, val, true
}

func newestArchivedMatch(archiveAbs, match string) string {
	entries, err := os.ReadDir(archiveAbs)
	if err != nil {
		return ""
	}
	var best string
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		name := entry.Name()
		if (name == match || strings.HasSuffix(name, "-"+match)) && canonicalDecisionName(name) == match && name > best {
			best = name
		}
	}
	return best
}

func resolveDecisionHeaderRef(storeRoot, relPath, val string) string {
	trimmed := strings.TrimSpace(val)
	if trimmed == "" || strings.EqualFold(trimmed, "none") {
		return ""
	}
	if m := inlineWikiRe.FindStringSubmatch(trimmed); m != nil {
		res := resolveWikilinkTarget(storeRoot, relPath, m[1])
		if !res.Broken {
			return res.Resolved
		}
		return ""
	}

	match := decisionFileRe.FindString(trimmed)
	if match == "" {
		return ""
	}
	scopeRel, ok := pathScopeRelDir(relPath)
	if !ok {
		return ""
	}

	activeCandidate := path.Join(scopeRel, dirActive, match)
	if _, err := store.ResolveSafeFile(storeRoot, activeCandidate); err == nil {
		return activeCandidate
	}

	best := newestArchivedMatch(filepath.Join(storeRoot, filepath.FromSlash(path.Join(scopeRel, dirArchive))), match)
	if best == "" {
		return ""
	}
	archCandidate := path.Join(scopeRel, dirArchive, best)
	if _, err := store.ResolveSafeFile(storeRoot, archCandidate); err == nil {
		return archCandidate
	}
	return ""
}

func resolveSourceItem(storeRoot, relPath, scopeRel string, hasScope bool, rawPart string) (SourceLink, bool) {
	item := strings.TrimSpace(strings.Trim(strings.TrimSpace(rawPart), "`"))
	if item == "" {
		return SourceLink{}, false
	}
	if m := inlineWikiRe.FindStringSubmatch(item); m != nil {
		res := resolveWikilinkTarget(storeRoot, relPath, m[1])
		label := m[1]
		if m[2] != "" {
			label = m[2]
		}
		return SourceLink{
			Label:      label,
			TargetPath: res.Resolved,
			Broken:     res.Broken,
		}, true
	}
	if hasScope && !strings.HasPrefix(item, "/") && !strings.Contains(item, "..") {
		candidate := path.Clean(path.Join(scopeRel, item))
		if _, err := store.ResolveSafeFile(storeRoot, candidate); err == nil {
			return SourceLink{
				Label:      item,
				TargetPath: candidate,
			}, true
		}
	}
	return SourceLink{Label: item, Broken: true}, true
}

func resolveSources(storeRoot, relPath, val string) []SourceLink {
	trimmed := strings.TrimSpace(val)
	if trimmed == "" || strings.EqualFold(trimmed, "none") {
		return make([]SourceLink, 0)
	}
	scopeRel, hasScope := scopeRootRelDir(relPath)
	parts := strings.Split(val, ",")
	out := make([]SourceLink, 0, len(parts))

	for _, rawPart := range parts {
		if item, ok := resolveSourceItem(storeRoot, relPath, scopeRel, hasScope, rawPart); ok {
			out = append(out, item)
		}
	}
	return out
}

// scopeRootRelDir returns repos/<repo_id> or pinned/<slug> for a store-relative path.
func scopeRootRelDir(relPath string) (string, bool) {
	parts := strings.Split(path.Clean(relPath), "/")
	if len(parts) >= 2 && (parts[0] == scopeRepos || parts[0] == scopePinned) {
		return path.Join(parts[0], parts[1]), true
	}
	return "", false
}
