package render

import (
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"

	"github.com/BaankeyBihari/memoir-skill/dashboard/internal/store"
)

// DecisionChain represents a connected supersession graph across active and archived decisions.
type DecisionChain struct {
	Nodes []DecisionNode `json:"nodes"`
	Edges []DecisionEdge `json:"edges"`
}

// DecisionNode represents a decision fragment in a supersession chain.
type DecisionNode struct {
	ID         string `json:"id"`
	Title      string `json:"title"`
	Path       string `json:"path"`
	Date       string `json:"date,omitempty"`
	Archived   bool   `json:"archived,omitempty"`
	Current    bool   `json:"current,omitempty"`
	ActiveHead bool   `json:"active_head,omitempty"`
	Missing    bool   `json:"missing,omitempty"`
}

// DecisionEdge links an older decision (From) to the newer decision (To) that superseded it.
type DecisionEdge struct {
	From string `json:"from"`
	To   string `json:"to"`
}

// BuildDecisionChain constructs the connected supersession chain containing relPath
// across sibling active/ and archive/ decision-*.md files.
func BuildDecisionChain(storeRoot, relPath string) (*DecisionChain, error) {
	cleanRel := path.Clean(relPath)
	kind, _ := store.ClassifyFile(cleanRel)
	if kind != "decision" {
		return nil, nil
	}

	scopeRel, ok := pathScopeRelDir(cleanRel)
	if !ok {
		return nil, nil
	}
	currentID := canonicalDecisionName(path.Base(cleanRel))

	nodesByID := make(map[string]DecisionNode)
	edgeSet := make(map[DecisionEdge]bool)

	for _, dirInfo := range []struct {
		sub      string
		archived bool
	}{
		{sub: "archive", archived: true},
		{sub: "active", archived: false},
	} {
		dirAbs := filepath.Join(storeRoot, filepath.FromSlash(path.Join(scopeRel, dirInfo.sub)))
		entries, err := os.ReadDir(dirAbs)
		if err != nil {
			continue
		}
		sort.Slice(entries, func(i, j int) bool {
			return entries[i].Name() < entries[j].Name()
		})

		for _, entry := range entries {
			if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".md") {
				continue
			}
			canon := canonicalDecisionName(entry.Name())
			if !strings.HasPrefix(canon, "decision-") {
				continue
			}

			fileRel := path.Join(scopeRel, dirInfo.sub, entry.Name())
			fileAbs := filepath.Join(dirAbs, entry.Name())
			rawBytes, err := os.ReadFile(fileAbs)
			if err != nil {
				continue
			}

			parsed := parseHeaderAndBody(storeRoot, fileRel, string(rawBytes))
			dateVal := ""
			for _, b := range parsed.Badges {
				switch b.Key {
				case "Date":
					dateVal = b.Value
				case "Supersedes":
					for _, older := range extractDecisionTargets(b.Value, canon) {
						edgeSet[DecisionEdge{From: older, To: canon}] = true
					}
				case "Superseded-By":
					for _, newer := range extractDecisionTargets(b.Value, canon) {
						edgeSet[DecisionEdge{From: canon, To: newer}] = true
					}
				}
			}

			existing, exists := nodesByID[canon]
			// Active file supersedes archived copy if both briefly coexist; newer archive wins among archives.
			if !exists || (!dirInfo.archived && existing.Archived) || (dirInfo.archived && existing.Archived && entry.Name() > path.Base(existing.Path)) {
				nodesByID[canon] = DecisionNode{
					ID:       canon,
					Title:    parsed.Title,
					Path:     fileRel,
					Date:     dateVal,
					Archived: dirInfo.archived,
					Current:  fileRel == cleanRel,
				}
			}
		}
	}

	if len(edgeSet) == 0 {
		return nil, nil
	}

	// Ensure referenced missing nodes are represented.
	for edge := range edgeSet {
		if _, ok := nodesByID[edge.From]; !ok {
			nodesByID[edge.From] = DecisionNode{
				ID:      edge.From,
				Title:   strings.TrimSuffix(edge.From, ".md"),
				Missing: true,
			}
		}
		if _, ok := nodesByID[edge.To]; !ok {
			nodesByID[edge.To] = DecisionNode{
				ID:      edge.To,
				Title:   strings.TrimSuffix(edge.To, ".md"),
				Missing: true,
			}
		}
	}

	// Find connected component containing currentID via undirected BFS.
	adjUndir := make(map[string][]string)
	for edge := range edgeSet {
		adjUndir[edge.From] = append(adjUndir[edge.From], edge.To)
		adjUndir[edge.To] = append(adjUndir[edge.To], edge.From)
	}
	if len(adjUndir[currentID]) == 0 {
		return nil, nil
	}

	component := make(map[string]bool)
	queue := []string{currentID}
	component[currentID] = true
	for len(queue) > 0 {
		cur := queue[0]
		queue = queue[1:]
		for _, nxt := range adjUndir[cur] {
			if !component[nxt] {
				component[nxt] = true
				queue = append(queue, nxt)
			}
		}
	}

	var edges []DecisionEdge
	outDeg := make(map[string]int)
	inDeg := make(map[string]int)
	adjOut := make(map[string][]string)

	for edge := range edgeSet {
		if component[edge.From] && component[edge.To] {
			edges = append(edges, edge)
			outDeg[edge.From]++
			inDeg[edge.To]++
			adjOut[edge.From] = append(adjOut[edge.From], edge.To)
		}
	}
	sort.Slice(edges, func(i, j int) bool {
		if edges[i].From != edges[j].From {
			return edges[i].From < edges[j].From
		}
		return edges[i].To < edges[j].To
	})

	// Topological sort (oldest -> newest) with cycle protection.
	orderedIDs := topoSortComponent(component, inDeg, adjOut)
	nodes := make([]DecisionNode, 0, len(orderedIDs))
	for _, id := range orderedIDs {
		node := nodesByID[id]
		if !node.Missing && !node.Archived && outDeg[id] == 0 {
			node.ActiveHead = true
		}
		if node.Path == cleanRel {
			node.Current = true
		}
		nodes = append(nodes, node)
	}

	return &DecisionChain{
		Nodes: nodes,
		Edges: edges,
	}, nil
}

func topoSortComponent(component map[string]bool, inDeg map[string]int, adjOut map[string][]string) []string {
	remaining := make(map[string]bool, len(component))
	for k := range component {
		remaining[k] = true
	}

	ordered := make([]string, 0, len(component))
	for len(remaining) > 0 {
		var ready []string
		for id := range remaining {
			if inDeg[id] == 0 {
				ready = append(ready, id)
			}
		}
		sort.Strings(ready)

		if len(ready) == 0 {
			// Cycle detected: deterministically pick the smallest remaining ID to break it.
			var rest []string
			for id := range remaining {
				rest = append(rest, id)
			}
			sort.Strings(rest)
			ready = []string{rest[0]}
		}

		cur := ready[0]
		ordered = append(ordered, cur)
		delete(remaining, cur)
		for _, nxt := range adjOut[cur] {
			if inDeg[nxt] > 0 {
				inDeg[nxt]--
			}
		}
	}
	return ordered
}

func pathScopeRelDir(relPath string) (string, bool) {
	clean := path.Clean(relPath)
	dir := path.Dir(clean)
	baseDir := path.Base(dir)
	if baseDir != "active" && baseDir != "archive" {
		return "", false
	}
	return path.Dir(dir), true
}

func canonicalDecisionName(filename string) string {
	if len(filename) > 9 && filename[8] == '-' && isDigits(filename[:8]) {
		return filename[9:]
	}
	return filename
}

func extractDecisionTargets(val, selfID string) []string {
	matches := decisionFileRe.FindAllString(val, -1)
	seen := make(map[string]bool)
	var out []string
	for _, m := range matches {
		if m != selfID && !seen[m] {
			seen[m] = true
			out = append(out, m)
		}
	}
	return out
}

func isDigits(s string) bool {
	for i := 0; i < len(s); i++ {
		if s[i] < '0' || s[i] > '9' {
			return false
		}
	}
	return true
}
