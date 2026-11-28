// Package store scans, validates, indexes, and prunes local Memoir store directories.
package store

const (
	dirRepos          = "repos"
	dirPinned         = "pinned"
	dirStandalone     = "standalone"
	dirClones         = "clones"
	dirPaths          = "paths"
	dirActive         = "active"
	dirArchive        = "archive"
	dirWiki           = "wiki"
	fileCloneJSON     = "clone.json"
	fileWorkspaceJSON = "workspace.json"
	fileScopeJSON     = "scope.json"
	filePinnedJSON    = "pinned.json"
	fileMetaJSON      = "meta.json"
	fileStateCurrent  = "state-current.md"
	keyMain           = "_main"
	keyRoot           = "_root"
	labelRoot         = "root"
	scopeRepo         = "repo"
	extMD             = ".md"
)

// Tree represents the hierarchical contents of a Memoir store root.
type Tree struct {
	StoreRoot  string            `json:"store_root"`
	Repos      []RepoScope       `json:"repos"`
	Pinned     []PinnedScope     `json:"pinned"`
	Standalone []StandaloneScope `json:"standalone"`
}

// RepoScope represents a Git repository scope under repos/<repo_id>.
type RepoScope struct {
	ID     string       `json:"id"`
	Label  string       `json:"label"`
	Meta   *RepoMeta    `json:"meta,omitempty"`
	Wiki   *WikiTree    `json:"wiki,omitempty"`
	Clones []CloneScope `json:"clones"`
}

// RepoMeta mirrors repos/<repo_id>/meta.json.
type RepoMeta struct {
	Remote     string `json:"remote,omitempty"`
	SyncToRepo bool   `json:"sync_to_repo,omitempty"`
	SyncTarget string `json:"sync_target,omitempty"`
}

// CloneScope represents a Git clone under repos/<repo_id>/clones/<clone_id>.
type CloneScope struct {
	ID       string      `json:"id"`
	Label    string      `json:"label"`
	RelPath  string      `json:"rel_path"`
	Root     string      `json:"root,omitempty"`
	LastSeen string      `json:"last_seen,omitempty"`
	Orphaned bool        `json:"orphaned,omitempty"`
	Paths    []PathScope `json:"paths"`
}

// PinnedScope represents a pinned non-Git workspace under pinned/<slug>.
type PinnedScope struct {
	ID       string      `json:"id"`
	Label    string      `json:"label"`
	RelPath  string      `json:"rel_path"`
	Root     string      `json:"root,omitempty"`
	LastSeen string      `json:"last_seen,omitempty"`
	Orphaned bool        `json:"orphaned,omitempty"`
	Wiki     *WikiTree   `json:"wiki,omitempty"`
	Paths    []PathScope `json:"paths"`
}

// StandaloneScope represents an unpinned non-Git directory under standalone/<slug>.
type StandaloneScope struct {
	ID      string     `json:"id"`
	Label   string     `json:"label"`
	State   *FileNode  `json:"state,omitempty"`
	Active  []FileNode `json:"active"`
	Archive []FileNode `json:"archive"`
}

// PathScope represents a checkout/worktree or workspace subpath with active and archived fragments.
type PathScope struct {
	Key     string     `json:"key"`
	Label   string     `json:"label"`
	State   *FileNode  `json:"state,omitempty"`
	Active  []FileNode `json:"active"`
	Archive []FileNode `json:"archive"`
}

// WikiTree holds the shared wiki pages and category folders for a repo or pinned scope.
type WikiTree struct {
	TopPages   []FileNode     `json:"top_pages"`
	Categories []WikiCategory `json:"categories"`
}

// WikiCategory groups Markdown pages inside a wiki subdirectory.
type WikiCategory struct {
	Name  string     `json:"name"`
	Pages []FileNode `json:"pages"`
}

// FileNode describes a Markdown fragment or wiki page in the store.
type FileNode struct {
	Name     string `json:"name"`
	Path     string `json:"path"`
	Title    string `json:"title"`
	Kind     string `json:"kind"`
	Archived bool   `json:"archived,omitempty"`
}
