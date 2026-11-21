package render

import (
	"os"
	"path"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/BaankeyBihari/memoir-skill/dashboard/internal/store"
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
	"Date":          true,
	"Updated":       true,
	"Type":          true,
	"Status":        true,
	"Target":        true,
	"Supersedes":    true,
	"Superseded-By": true,
	"Sources":       true,
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

func parseHeaderAndBody(storeRoot, relPath, raw string) parsedDoc {
	norm := strings.ReplaceAll(raw, "\r\n", "\n")
	lines := strings.Split(norm, "\n")

	title := ""
	idx := 0
	for idx < len(lines) && strings.TrimSpace(lines[idx]) == "" {
		idx++
	}
	if idx < len(lines) && strings.HasPrefix(strings.TrimSpace(lines[idx]), "# ") {
		title = strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(lines[idx]), "# "))
		idx++
	}
	if title == "" {
		title = strings.TrimSuffix(path.Base(relPath), ".md")
	}

	rawFields := make(map[string]string)
	fieldOrder := make([]string, 0)
	bodyFieldLines := make([]string, 0)

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

	// Wiki entity pages place `Target:` right after a blank line below `Sources:`.
	if _, hasTarget := rawFields["Target"]; !hasTarget && rawFields["Type"] == "entity" {
		peek := idx
		for peek < len(lines) && strings.TrimSpace(lines[peek]) == "" {
			peek++
		}
		if peek < len(lines) {
			if key, val, ok := splitHeaderLine(strings.TrimSpace(lines[peek])); ok && key == "Target" {
				rawFields["Target"] = val
				fieldOrder = append(fieldOrder, "Target")
				idx = peek + 1
			}
		}
	}

	badges := make([]MetadataBadge, 0, len(fieldOrder))
	sources := make([]SourceLink, 0)

	for _, key := range fieldOrder {
		val := rawFields[key]
		if key == "Sources" {
			sources = resolveSources(storeRoot, relPath, val)
			continue
		}
		badge := MetadataBadge{
			Key:   key,
			Value: val,
		}
		switch key {
		case "Target":
			if strings.HasPrefix(val, "http://") || strings.HasPrefix(val, "https://") {
				badge.URL = val
			}
		case "Supersedes", "Superseded-By":
			badge.TargetPath = resolveDecisionHeaderRef(storeRoot, relPath, val)
		}
		badges = append(badges, badge)
	}

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

	activeCandidate := path.Join(scopeRel, "active", match)
	if _, err := store.ResolveSafeFile(storeRoot, activeCandidate); err == nil {
		return activeCandidate
	}

	archiveAbs := filepath.Join(storeRoot, filepath.FromSlash(path.Join(scopeRel, "archive")))
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
		if name == match || strings.HasSuffix(name, "-"+match) {
			if canonicalDecisionName(name) == match && name > best {
				best = name
			}
		}
	}
	if best == "" {
		return ""
	}
	archCandidate := path.Join(scopeRel, "archive", best)
	if _, err := store.ResolveSafeFile(storeRoot, archCandidate); err == nil {
		return archCandidate
	}
	return ""
}

func resolveSources(storeRoot, relPath, val string) []SourceLink {
	if strings.TrimSpace(val) == "" || strings.EqualFold(strings.TrimSpace(val), "none") {
		return make([]SourceLink, 0)
	}
	scopeRel, hasScope := scopeRootRelDir(relPath)
	parts := strings.Split(val, ",")
	out := make([]SourceLink, 0, len(parts))

	for _, rawPart := range parts {
		item := strings.TrimSpace(rawPart)
		item = strings.Trim(item, "`")
		item = strings.TrimSpace(item)
		if item == "" {
			continue
		}

		if m := inlineWikiRe.FindStringSubmatch(item); m != nil {
			res := resolveWikilinkTarget(storeRoot, relPath, m[1])
			label := m[1]
			if m[2] != "" {
				label = m[2]
			}
			out = append(out, SourceLink{
				Label:      label,
				TargetPath: res.Resolved,
				Broken:     res.Broken,
			})
			continue
		}

		if hasScope && !strings.HasPrefix(item, "/") && !strings.Contains(item, "..") {
			candidate := path.Clean(path.Join(scopeRel, item))
			if _, err := store.ResolveSafeFile(storeRoot, candidate); err == nil {
				out = append(out, SourceLink{
					Label:      item,
					TargetPath: candidate,
				})
				continue
			}
		}
		out = append(out, SourceLink{
			Label:  item,
			Broken: true,
		})
	}
	return out
}

// scopeRootRelDir returns repos/<repo_id> or pinned/<slug> for a store-relative path.
func scopeRootRelDir(relPath string) (string, bool) {
	parts := strings.Split(path.Clean(relPath), "/")
	if len(parts) >= 2 && (parts[0] == "repos" || parts[0] == "pinned") {
		return path.Join(parts[0], parts[1]), true
	}
	return "", false
}
