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
	nodesByID, edgeSet := scanScopeDecisions(storeRoot, scopeRel, cleanRel)
	if len(edgeSet) == 0 {
		return nil, nil
	}

	addMissingDecisionNodes(nodesByID, edgeSet)
	component := connectedDecisionComponent(currentID, edgeSet)
	if len(component) == 0 {
		return nil, nil
	}

	edges, outDeg, inDeg, adjOut := buildComponentEdges(component, edgeSet)
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

func scanScopeDecisions(storeRoot, scopeRel, cleanRel string) (map[string]DecisionNode, map[DecisionEdge]bool) {
	nodesByID := make(map[string]DecisionNode)
	edgeSet := make(map[DecisionEdge]bool)
	for _, dirInfo := range []struct {
		sub      string
		archived bool
	}{
		{sub: dirArchive, archived: true},
		{sub: dirActive, archived: false},
	} {
		scanDecisionSubdir(storeRoot, scopeRel, dirInfo.sub, cleanRel, dirInfo.archived, nodesByID, edgeSet)
	}
	return nodesByID, edgeSet
}

func ingestDecisionFile(
	storeRoot, scopeRel, sub, cleanRel, dirAbs, entryName string,
	archived bool,
	nodesByID map[string]DecisionNode,
	edgeSet map[DecisionEdge]bool,
) {
	if !strings.HasSuffix(entryName, extMD) {
		return
	}
	canon := canonicalDecisionName(entryName)
	if !strings.HasPrefix(canon, "decision-") {
		return
	}
	fileRel := path.Join(scopeRel, sub, entryName)
	rawBytes, err := os.ReadFile(filepath.Join(dirAbs, entryName))
	if err != nil {
		return
	}

	parsed := parseHeaderAndBody(storeRoot, fileRel, string(rawBytes))
	dateVal := collectDecisionEdges(parsed.Badges, canon, edgeSet)
	if existing, exists := nodesByID[canon]; shouldReplaceDecisionNode(existing, exists, archived, entryName) {
		nodesByID[canon] = DecisionNode{
			ID:       canon,
			Title:    parsed.Title,
			Path:     fileRel,
			Date:     dateVal,
			Archived: archived,
			Current:  fileRel == cleanRel,
		}
	}
}

func scanDecisionSubdir(
	storeRoot, scopeRel, sub, cleanRel string,
	archived bool,
	nodesByID map[string]DecisionNode,
	edgeSet map[DecisionEdge]bool,
) {
	dirAbs := filepath.Join(storeRoot, filepath.FromSlash(path.Join(scopeRel, sub)))
	entries, err := os.ReadDir(dirAbs)
	if err != nil {
		return
	}
	sort.Slice(entries, func(i, j int) bool {
		return entries[i].Name() < entries[j].Name()
	})

	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		ingestDecisionFile(storeRoot, scopeRel, sub, cleanRel, dirAbs, entry.Name(), archived, nodesByID, edgeSet)
	}
}

func collectDecisionEdges(badges []MetadataBadge, canon string, edgeSet map[DecisionEdge]bool) string {
	dateVal := ""
	for _, b := range badges {
		switch b.Key {
		case hdrDate:
			dateVal = b.Value
		case hdrSupersedes:
			for _, older := range extractDecisionTargets(b.Value, canon) {
				edgeSet[DecisionEdge{From: older, To: canon}] = true
			}
		case hdrSupersededBy:
			for _, newer := range extractDecisionTargets(b.Value, canon) {
				edgeSet[DecisionEdge{From: canon, To: newer}] = true
			}
		}
	}
	return dateVal
}

func shouldReplaceDecisionNode(existing DecisionNode, exists, archived bool, entryName string) bool {
	if !exists {
		return true
	}
	// Active file supersedes archived copy if both briefly coexist; newer archive wins among archives.
	if !archived && existing.Archived {
		return true
	}
	return archived && existing.Archived && entryName > path.Base(existing.Path)
}

func addMissingDecisionNodes(nodesByID map[string]DecisionNode, edgeSet map[DecisionEdge]bool) {
	ensureMissing := func(id string) {
		if _, ok := nodesByID[id]; !ok {
			nodesByID[id] = DecisionNode{
				ID:      id,
				Title:   strings.TrimSuffix(id, extMD),
				Missing: true,
			}
		}
	}
	for edge := range edgeSet {
		ensureMissing(edge.From)
		ensureMissing(edge.To)
	}
}

func connectedDecisionComponent(currentID string, edgeSet map[DecisionEdge]bool) map[string]bool {
	adjUndir := make(map[string][]string)
	for edge := range edgeSet {
		adjUndir[edge.From] = append(adjUndir[edge.From], edge.To)
		adjUndir[edge.To] = append(adjUndir[edge.To], edge.From)
	}
	if len(adjUndir[currentID]) == 0 {
		return nil
	}

	component := map[string]bool{currentID: true}
	for queue := []string{currentID}; len(queue) > 0; {
		cur := queue[0]
		queue = queue[1:]
		for _, nxt := range adjUndir[cur] {
			if !component[nxt] {
				component[nxt] = true
				queue = append(queue, nxt)
			}
		}
	}
	return component
}

func buildComponentEdges(component map[string]bool, edgeSet map[DecisionEdge]bool) ([]DecisionEdge, map[string]int, map[string]int, map[string][]string) {
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
	return edges, outDeg, inDeg, adjOut
}

func nextTopoNode(remaining map[string]bool, inDeg map[string]int) string {
	var ready []string
	var all []string
	for id := range remaining {
		all = append(all, id)
		if inDeg[id] == 0 {
			ready = append(ready, id)
		}
	}
	if len(ready) > 0 {
		sort.Strings(ready)
		return ready[0]
	}
	// Cycle detected: deterministically pick the smallest remaining ID to break it.
	sort.Strings(all)
	return all[0]
}

func topoSortComponent(component map[string]bool, inDeg map[string]int, adjOut map[string][]string) []string {
	remaining := make(map[string]bool, len(component))
	for k := range component {
		remaining[k] = true
	}

	ordered := make([]string, 0, len(component))
	for len(remaining) > 0 {
		cur := nextTopoNode(remaining, inDeg)
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
	if baseDir != dirActive && baseDir != dirArchive {
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
