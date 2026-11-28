package render

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func writeTestFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		t.Fatalf("mkdir %s: %v", filepath.Dir(path), err)
	}
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatalf("write %s: %v", path, err)
	}
}

func TestRenderHeadersAndBadges(t *testing.T) {
	storeRoot := t.TempDir()

	// Reference fragment with Target URL.
	refRel := "repos/github.com__acme__app/clones/app--11111111/paths/_main/active/reference-go.md"
	refRaw := "# Go Spec\nTarget: https://go.dev/ref/spec\nWhy: Language semantics reference.\n"
	writeTestFile(t, filepath.Join(storeRoot, refRel), refRaw)

	doc, err := RenderDocument(storeRoot, refRel, refRaw)
	if err != nil {
		t.Fatalf("RenderDocument ref: %v", err)
	}
	if doc.Title != "Go Spec" {
		t.Fatalf("Title = %q, want Go Spec", doc.Title)
	}
	if len(doc.Badges) != 1 || doc.Badges[0].Key != "Target" || doc.Badges[0].URL != "https://go.dev/ref/spec" {
		t.Fatalf("unexpected badges: %+v", doc.Badges)
	}
	if !strings.Contains(doc.HTML, "<strong>Why:</strong> Language semantics reference.") {
		t.Fatalf("expected formatted Why paragraph in HTML, got %q", doc.HTML)
	}

	// Wiki entity page with Target after blank line and Sources resolution.
	entityRel := "repos/github.com__acme__app/wiki/entities/go-spec.md"
	entityRaw := "# Go Spec\nType: entity\nUpdated: 2026-11-21\nSources: clones/app--11111111/paths/_main/active/reference-go.md, missing/file.md\n\nTarget: https://go.dev/ref/spec\nOfficial spec.\n"
	writeTestFile(t, filepath.Join(storeRoot, entityRel), entityRaw)

	entDoc, err := RenderDocument(storeRoot, entityRel, entityRaw)
	if err != nil {
		t.Fatalf("RenderDocument entity: %v", err)
	}
	if len(entDoc.Sources) != 2 || entDoc.Sources[0].Broken || entDoc.Sources[0].TargetPath != refRel || !entDoc.Sources[1].Broken {
		t.Fatalf("unexpected resolved sources: %+v", entDoc.Sources)
	}
	foundTarget := false
	for _, b := range entDoc.Badges {
		if b.Key == "Target" && b.URL == "https://go.dev/ref/spec" {
			foundTarget = true
		}
	}
	if !foundTarget {
		t.Fatalf("expected Target badge on entity wiki page, got %+v", entDoc.Badges)
	}
}

func TestRenderMarkdownWikilinksAndSafety(t *testing.T) {
	storeRoot := t.TempDir()

	mainWiki := "repos/github.com__acme__app/wiki"
	otherWiki := "pinned/research--4d5e6f7a/wiki"
	writeTestFile(t, filepath.Join(storeRoot, mainWiki, "decisions/store-location.md"), "# Store Location\n")
	writeTestFile(t, filepath.Join(storeRoot, otherWiki, "architecture/notes.md"), "# Research Notes\n")

	pageRel := mainWiki + "/index.md"
	raw := `# Wiki Index
Updated: 2026-11-21

- Local: [[decisions/store-location]] and [[decisions/store-location|store loc]]
- Cross: [[research--4d5e6f7a:architecture/notes#sec]]
- Broken: [[decisions/does-not-exist]]
- Code span: ` + "`[[decisions/store-location]]`" + `

` + "```markdown\n[[decisions/store-location]]\n```" + `

<script>alert("xss")</script>
`
	writeTestFile(t, filepath.Join(storeRoot, pageRel), raw)

	doc, err := RenderDocument(storeRoot, pageRel, raw)
	if err != nil {
		t.Fatalf("RenderDocument: %v", err)
	}

	if !strings.Contains(doc.HTML, `class="wikilink" href="#file=repos%2Fgithub.com__acme__app%2Fwiki%2Fdecisions%2Fstore-location.md"`) {
		t.Fatalf("missing local wikilink anchor in HTML:\n%s", doc.HTML)
	}
	if !strings.Contains(doc.HTML, `>store loc</a>`) {
		t.Fatalf("missing labeled wikilink in HTML:\n%s", doc.HTML)
	}
	if !strings.Contains(doc.HTML, `class="wikilink wikilink-cross" href="#file=pinned%2Fresearch--4d5e6f7a%2Fwiki%2Farchitecture%2Fnotes.md" data-path="pinned/research--4d5e6f7a/wiki/architecture/notes.md" data-scope="research--4d5e6f7a" data-anchor="sec"`) {
		t.Fatalf("missing cross-wiki link in HTML:\n%s", doc.HTML)
	}
	if !strings.Contains(doc.HTML, `<span class="wikilink wikilink-broken" title="Broken wikilink: decisions/does-not-exist">decisions/does-not-exist</span>`) {
		t.Fatalf("missing broken wikilink span in HTML:\n%s", doc.HTML)
	}
	// Inline code span and fenced code block must remain literal text, not <a>.
	if !strings.Contains(doc.HTML, `<code>[[decisions/store-location]]</code>`) {
		t.Fatalf("code span wikilink was unexpectedly transformed:\n%s", doc.HTML)
	}
	if strings.Contains(doc.HTML, "<script>") {
		t.Fatalf("raw HTML script tag must be escaped by goldmark:\n%s", doc.HTML)
	}
}

func TestComputeBacklinksLocalCrossWikiAndCodeExclusion(t *testing.T) {
	storeRoot := t.TempDir()
	repoWiki := "repos/github.com__acme__app/wiki"
	pinWiki := "pinned/research--4d5e6f7a/wiki"

	targetRel := repoWiki + "/decisions/auth.md"
	writeTestFile(t, filepath.Join(storeRoot, targetRel), "# Auth Decision\nSee [[decisions/auth]] (self).\n")
	writeTestFile(t, filepath.Join(storeRoot, repoWiki, "architecture/overview.md"), "# Overview\nUses [[decisions/auth|JWT auth]].\n")
	writeTestFile(t, filepath.Join(storeRoot, repoWiki, "index.md"), "# Wiki Index\n- [[decisions/auth]]: auth\n")
	writeTestFile(t, filepath.Join(storeRoot, repoWiki, "log.md"), "# Wiki Log\n- updated [[decisions/auth]]\n")
	writeTestFile(t, filepath.Join(storeRoot, repoWiki, "entities/ignored.md"), "# Ignored\nCode only: `[[decisions/auth]]`\n")
	writeTestFile(t, filepath.Join(storeRoot, pinWiki, "architecture/cross.md"), "# Cross\nDepends on [[github.com__acme__app:decisions/auth]].\n")

	links, err := ComputeBacklinks(storeRoot, targetRel)
	if err != nil {
		t.Fatalf("ComputeBacklinks: %v", err)
	}
	if len(links) != 4 {
		t.Fatalf("expected 4 backlinks (overview, cross, index, log), got %d: %+v", len(links), links)
	}
	// Content pages must sort before index and log.
	if links[0].Kind != "page" || links[1].Kind != "page" || links[2].Kind != "index" || links[3].Kind != "log" {
		t.Fatalf("unexpected backlink order: %+v", links)
	}
	foundCross := false
	for _, bl := range links {
		if bl.SourcePath == pinWiki+"/architecture/cross.md" {
			foundCross = bl.CrossWiki && bl.SourceScope == "research--4d5e6f7a"
		}
	}
	if !foundCross {
		t.Fatalf("expected cross-wiki backlink metadata, got %+v", links)
	}
}

func TestBuildDecisionChainMultiHopMissingAndCycleSafe(t *testing.T) {
	storeRoot := t.TempDir()
	pathBase := "repos/github.com__acme__app/clones/app--11111111/paths/_main"

	v1 := pathBase + "/archive/20261101-decision-v1.md"
	v2 := pathBase + "/archive/20261110-decision-v2.md"
	v3 := pathBase + "/active/decision-v3.md"
	standaloneDec := pathBase + "/active/decision-unrelated.md"

	writeTestFile(t, filepath.Join(storeRoot, v1), "# Use SQLite\nDate: 2026-11-01\nSupersedes: none\nSuperseded-By: decision-v2.md\n")
	writeTestFile(t, filepath.Join(storeRoot, v2), "# Use Postgres\nDate: 2026-11-10\nSupersedes: decision-v1.md\nSuperseded-By: decision-v3.md\n")
	writeTestFile(t, filepath.Join(storeRoot, v3), "# Use Embedded Store\nDate: 2026-11-21\nSupersedes: decision-v2.md\n")
	writeTestFile(t, filepath.Join(storeRoot, standaloneDec), "# Unrelated\nDate: 2026-11-21\nSupersedes: none\n")

	chain, err := BuildDecisionChain(storeRoot, v2)
	if err != nil {
		t.Fatalf("BuildDecisionChain v2: %v", err)
	}
	if chain == nil || len(chain.Nodes) != 3 || len(chain.Edges) != 2 {
		t.Fatalf("unexpected chain: %+v", chain)
	}
	if chain.Nodes[0].ID != "decision-v1.md" || chain.Nodes[1].ID != "decision-v2.md" || chain.Nodes[2].ID != "decision-v3.md" {
		t.Fatalf("expected oldest-to-newest topo order, got %+v", chain.Nodes)
	}
	if !chain.Nodes[1].Current || !chain.Nodes[2].ActiveHead || !chain.Nodes[0].Archived {
		t.Fatalf("unexpected node flags: %+v", chain.Nodes)
	}

	// Unrelated decision with no supersession links yields nil chain.
	noneChain, err := BuildDecisionChain(storeRoot, standaloneDec)
	if err != nil || noneChain != nil {
		t.Fatalf("expected nil chain for unrelated decision, got %+v, err=%v", noneChain, err)
	}

	// Missing ancestor + cycle safety test.
	cycBase := "standalone/scratch--12345678"
	c1 := cycBase + "/active/decision-cycle-a.md"
	c2 := cycBase + "/active/decision-cycle-b.md"
	writeTestFile(t, filepath.Join(storeRoot, c1), "# Cycle A\nSupersedes: decision-cycle-b.md, decision-ghost.md\n")
	writeTestFile(t, filepath.Join(storeRoot, c2), "# Cycle B\nSupersedes: decision-cycle-a.md\n")

	cycChain, err := BuildDecisionChain(storeRoot, c1)
	if err != nil {
		t.Fatalf("BuildDecisionChain cycle: %v", err)
	}
	if cycChain == nil || len(cycChain.Nodes) != 3 {
		t.Fatalf("expected 3 nodes (including missing ghost) in cycle-safe chain, got %+v", cycChain)
	}
	if !cycChain.Nodes[0].Missing || cycChain.Nodes[0].ID != "decision-ghost.md" {
		t.Fatalf("expected missing ghost node sorted first, got %+v", cycChain.Nodes[0])
	}
}
