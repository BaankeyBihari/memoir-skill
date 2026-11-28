// Package render parses Memoir headers, wikilinks, backlinks, and decision chains into HTML and metadata.
package render

import (
	"bytes"

	"github.com/yuin/goldmark"
	"github.com/yuin/goldmark/extension"
	"github.com/yuin/goldmark/parser"
)

// Document holds the rendered HTML and metadata extracted for a Markdown file.
type Document struct {
	Title         string          `json:"title"`
	HTML          string          `json:"html"`
	Badges        []MetadataBadge `json:"badges"`
	Sources       []SourceLink    `json:"sources"`
	Backlinks     []Backlink      `json:"backlinks"`
	DecisionChain *DecisionChain  `json:"decision_chain,omitempty"`
}

// RenderDocument parses headers, renders safe GFM Markdown with [[wikilinks]],
// and computes wiki backlinks or decision supersession chains as applicable.
func RenderDocument(storeRoot, relPath, raw string) (*Document, error) {
	parsed := parseHeaderAndBody(storeRoot, relPath, raw)

	md := goldmark.New(
		goldmark.WithExtensions(
			extension.GFM,
			&WikilinkExtension{
				StoreRoot:      storeRoot,
				CurrentRelPath: relPath,
			},
		),
		goldmark.WithParserOptions(
			parser.WithAutoHeadingID(),
		),
	)

	var buf bytes.Buffer
	if err := md.Convert([]byte(parsed.BodyMarkdown), &buf); err != nil {
		return nil, err
	}

	backlinks, err := ComputeBacklinks(storeRoot, relPath)
	if err != nil {
		backlinks = make([]Backlink, 0)
	}

	chain, err := BuildDecisionChain(storeRoot, relPath)
	if err != nil {
		chain = nil
	}

	return &Document{
		Title:         parsed.Title,
		HTML:          buf.String(),
		Badges:        parsed.Badges,
		Sources:       parsed.Sources,
		Backlinks:     backlinks,
		DecisionChain: chain,
	}, nil
}
