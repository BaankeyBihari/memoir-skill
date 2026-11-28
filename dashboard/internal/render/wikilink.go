package render

import (
	"fmt"
	"html"
	"net/url"
	"path"
	"strings"

	"github.com/BaankeyBihari/memoir-skill/dashboard/internal/store"
	"github.com/yuin/goldmark"
	"github.com/yuin/goldmark/ast"
	"github.com/yuin/goldmark/parser"
	"github.com/yuin/goldmark/renderer"
	"github.com/yuin/goldmark/text"
	"github.com/yuin/goldmark/util"
)

// KindWikilink is the Goldmark AST node kind for [[wikilinks]].
var KindWikilink = ast.NewNodeKind("Wikilink")

// ParsedLink describes a resolved or broken wikilink extracted from Markdown.
type ParsedLink struct {
	RawTarget string
	Scope     string
	Page      string
	Anchor    string
	Label     string
	Resolved  string
	CrossWiki bool
	Broken    bool
	Snippet   string
}

// WikilinkNode is a Goldmark inline AST node for [[page]] and [[scope:page]] links.
type WikilinkNode struct {
	ast.BaseInline
	Link ParsedLink
}

// Kind implements ast.Node.
func (n *WikilinkNode) Kind() ast.NodeKind {
	return KindWikilink
}

// Dump implements ast.Node.
func (n *WikilinkNode) Dump(source []byte, level int) {
	ast.DumpHelper(n, source, level, map[string]string{
		hdrTarget: n.Link.RawTarget,
		"Label":   n.Link.Label,
	}, nil)
}

type wikilinkParser struct {
	storeRoot      string
	currentRelPath string
}

func (p *wikilinkParser) Trigger() []byte {
	return []byte{'['}
}

func (p *wikilinkParser) Parse(_ ast.Node, block text.Reader, _ parser.Context) ast.Node {
	line, _ := block.PeekLine()
	if len(line) < 5 || line[0] != '[' || line[1] != '[' || line[2] == '[' {
		return nil
	}

	end := -1
	for i := 2; i+1 < len(line); i++ {
		if line[i] == '\n' || line[i] == '\r' || line[i] == '[' {
			return nil
		}
		if line[i] == ']' && line[i+1] == ']' {
			end = i
			break
		}
	}
	if end <= 2 {
		return nil
	}

	rawInner := string(line[2:end])
	link := parseAndResolveWikilink(p.storeRoot, p.currentRelPath, rawInner)
	if link.Page == "" {
		return nil
	}

	block.Advance(end + 2)
	return &WikilinkNode{Link: link}
}

type wikilinkRenderer struct{}

func (r *wikilinkRenderer) RegisterFuncs(reg renderer.NodeRendererFuncRegisterer) {
	reg.Register(KindWikilink, r.renderWikilink)
}

func (r *wikilinkRenderer) renderWikilink(w util.BufWriter, _ []byte, node ast.Node, entering bool) (ast.WalkStatus, error) {
	if !entering {
		return ast.WalkContinue, nil
	}
	n, ok := node.(*WikilinkNode)
	if !ok {
		return ast.WalkContinue, nil
	}
	link := n.Link

	if link.Broken {
		titleAttr := html.EscapeString("Broken wikilink: " + link.RawTarget)
		_, _ = fmt.Fprintf(w, `<span class="wikilink wikilink-broken" title="%s">%s</span>`,
			titleAttr, html.EscapeString(link.Label))
		return ast.WalkSkipChildren, nil
	}

	classes := "wikilink"
	scopeAttr := ""
	if link.CrossWiki {
		classes += " wikilink-cross"
		scopeAttr = fmt.Sprintf(` data-scope="%s"`, html.EscapeString(link.Scope))
	}
	anchorAttr := ""
	if link.Anchor != "" {
		anchorAttr = fmt.Sprintf(` data-anchor="%s"`, html.EscapeString(link.Anchor))
	}
	escapedPath := html.EscapeString(link.Resolved)
	href := "#file=" + encodeHashComponent(link.Resolved)

	_, _ = fmt.Fprintf(w, `<a class="%s" href="%s" data-path="%s"%s%s>%s</a>`,
		classes, href, escapedPath, scopeAttr, anchorAttr, html.EscapeString(link.Label))
	return ast.WalkSkipChildren, nil
}

// WikilinkExtension adds [[page]] and [[scope:page]] parsing and HTML rendering to Goldmark.
type WikilinkExtension struct {
	StoreRoot      string
	CurrentRelPath string
}

// Extend implements goldmark.Extender.
func (e *WikilinkExtension) Extend(m goldmark.Markdown) {
	m.Parser().AddOptions(
		parser.WithInlineParsers(
			util.Prioritized(&wikilinkParser{
				storeRoot:      e.StoreRoot,
				currentRelPath: e.CurrentRelPath,
			}, 100),
		),
	)
	m.Renderer().AddOptions(
		renderer.WithNodeRenderers(
			util.Prioritized(&wikilinkRenderer{}, 500),
		),
	)
}

// ExtractWikilinks parses raw Markdown with Goldmark and returns all non-code wikilinks.
func ExtractWikilinks(storeRoot, relPath, raw string) []ParsedLink {
	md := goldmark.New(
		goldmark.WithExtensions(&WikilinkExtension{
			StoreRoot:      storeRoot,
			CurrentRelPath: relPath,
		}),
	)
	src := []byte(strings.ReplaceAll(raw, "\r\n", "\n"))
	doc := md.Parser().Parse(text.NewReader(src))

	var links []ParsedLink
	_ = ast.Walk(doc, func(n ast.Node, entering bool) (ast.WalkStatus, error) {
		if !entering {
			return ast.WalkContinue, nil
		}
		if wl, ok := n.(*WikilinkNode); ok {
			link := wl.Link
			link.Snippet = extractParentSnippet(wl, src)
			links = append(links, link)
		}
		return ast.WalkContinue, nil
	})
	return links
}

func extractParentSnippet(node ast.Node, src []byte) string {
	cur := node.Parent()
	for cur != nil {
		if cur.Type() == ast.TypeBlock && cur.Lines() != nil && cur.Lines().Len() > 0 {
			textVal := strings.TrimSpace(string(cur.Lines().Value(src)))
			textVal = strings.Join(strings.Fields(textVal), " ")
			if len(textVal) > 160 {
				return textVal[:157] + "..."
			}
			return textVal
		}
		cur = cur.Parent()
	}
	return ""
}

func parseAndResolveWikilink(storeRoot, currentRelPath, rawInner string) ParsedLink {
	targetPart := rawInner
	labelPart := ""
	if idx := strings.IndexByte(rawInner, '|'); idx >= 0 {
		targetPart = rawInner[:idx]
		labelPart = strings.TrimSpace(rawInner[idx+1:])
	}

	targetPart = strings.TrimSpace(targetPart)
	anchorPart := ""
	if idx := strings.IndexByte(targetPart, '#'); idx >= 0 {
		anchorPart = strings.TrimSpace(targetPart[idx+1:])
		targetPart = strings.TrimSpace(targetPart[:idx])
	}

	res := resolveWikilinkTarget(storeRoot, currentRelPath, targetPart)
	label := labelPart
	if label == "" {
		if res.CrossWiki {
			label = res.Scope + ":" + res.Page
		} else {
			label = res.Page
		}
		if anchorPart != "" && label != "" {
			label += "#" + anchorPart
		}
	}

	return ParsedLink{
		RawTarget: targetPart,
		Scope:     res.Scope,
		Page:      res.Page,
		Anchor:    anchorPart,
		Label:     label,
		Resolved:  res.Resolved,
		CrossWiki: res.CrossWiki,
		Broken:    res.Broken,
	}
}

type resolvedTarget struct {
	Scope     string
	Page      string
	Resolved  string
	CrossWiki bool
	Broken    bool
}

func resolveCrossWikiTarget(storeRoot, scope, pagePath string) resolvedTarget {
	if scope == "" || !isCleanSegment(scope) {
		return resolvedTarget{Scope: scope, Page: pagePath, CrossWiki: true, Broken: true}
	}
	for _, kind := range []string{scopeRepos, scopePinned} {
		candidate := path.Join(kind, scope, dirWiki, pagePath+extMD)
		if _, err := store.ResolveSafeFile(storeRoot, candidate); err == nil {
			return resolvedTarget{
				Scope:     scope,
				Page:      pagePath,
				Resolved:  candidate,
				CrossWiki: true,
				Broken:    false,
			}
		}
	}
	return resolvedTarget{Scope: scope, Page: pagePath, CrossWiki: true, Broken: true}
}

func resolveWikilinkTarget(storeRoot, currentRelPath, target string) resolvedTarget {
	target = strings.TrimSpace(target)
	if target == "" || strings.Contains(target, "\\") || strings.HasPrefix(target, "/") {
		return resolvedTarget{Page: target, Broken: true}
	}

	var scope string
	pagePath := target
	cross := false
	if colon := strings.IndexByte(target, ':'); colon >= 0 {
		cross = true
		scope = strings.TrimSpace(target[:colon])
		pagePath = strings.TrimSpace(target[colon+1:])
	}

	pagePath = strings.TrimSuffix(pagePath, extMD)
	if pagePath == "" || !isCleanWikiPageRel(pagePath) {
		return resolvedTarget{Scope: scope, Page: pagePath, CrossWiki: cross, Broken: true}
	}

	if cross {
		return resolveCrossWikiTarget(storeRoot, scope, pagePath)
	}

	_, _, wikiRel, ok := WikiRootForPath(currentRelPath)
	if !ok {
		return resolvedTarget{Page: pagePath, Broken: true}
	}
	candidate := path.Join(wikiRel, pagePath+extMD)
	if _, err := store.ResolveSafeFile(storeRoot, candidate); err == nil {
		return resolvedTarget{
			Page:     pagePath,
			Resolved: candidate,
			Broken:   false,
		}
	}
	return resolvedTarget{Page: pagePath, Broken: true}
}

// WikiRootForPath extracts (scopeKind, scopeID, wikiRelPath, ok) for a store-relative wiki page path.
func WikiRootForPath(relPath string) (string, string, string, bool) {
	parts := strings.Split(path.Clean(relPath), "/")
	if len(parts) >= 4 && (parts[0] == scopeRepos || parts[0] == scopePinned) && parts[2] == dirWiki {
		return parts[0], parts[1], path.Join(parts[0], parts[1], dirWiki), true
	}
	return "", "", "", false
}

func isCleanSegment(seg string) bool {
	return seg != "" && seg != "." && seg != ".." && !strings.Contains(seg, "/") && !strings.HasPrefix(seg, ".")
}

func isCleanWikiPageRel(rel string) bool {
	parts := strings.Split(rel, "/")
	for _, seg := range parts {
		if seg == "" || seg == "." || seg == ".." || strings.HasPrefix(seg, ".") {
			return false
		}
	}
	return true
}

func encodeHashComponent(s string) string {
	return strings.ReplaceAll(url.QueryEscape(s), "+", "%20")
}
