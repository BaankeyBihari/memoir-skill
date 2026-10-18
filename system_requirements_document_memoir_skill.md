# System Requirements Document: Memoir Skill

## 1. Introduction

### 1.1 Purpose
This document outlines the system requirements, architecture, and design rationale for the **Memoir Skill**, a standalone state-management and context-compaction utility designed for extended LLM CLI sessions (e.g., Claude Code, Antigravity/Agy, OpenAI Codex).

### 1.2 Problem Statement
When using CLI-based LLMs for deep coding or architectural work, users encounter three major friction points:
1. **Context Entropy & Token Bloat:** As sessions grow, the LLM loses track of earlier decisions and current state, resulting in degraded reasoning, hallucination, and repetitive summarizing.
2. **Sandbox Restrictions:** Corporate or system sandboxes often prevent direct modification of global memory or configuration files, breaking traditional memory-management tools (like global MCP memory servers).
3. **Context Reset Friction:** Manually extracting decisions, summarizing the current state, and typing out paths to start a fresh, clean session is tedious. Developers often avoid clearing context until the LLM's output completely degrades.

### 1.3 Solution Overview
Memoir resolves these issues using a **project-scoped, CLI-driven local filesystem approach**. It abandons centralized MCP servers and global state files; a global store is used only outside Git and only when the user opts in (FR-1.1). Instead, it combines a strict LLM system prompt with a portable Python CLI script to write context fragments (decisions, state, logs) directly to the local Git repository. This allows developers to frequently `CLEAR` their LLM chat sessions and instantly `RESUME` with a perfectly curated context window.

## 2. System Architecture

The Memoir system relies on a dual-component architecture to ensure determinism and portability:

### 2.1 The Execution Engine (Python CLI)
A zero-dependency (or `uv`-bootstrapped via PEP 723) Python script (`memoir.py`) responsible for path resolution, directory initialization, file archiving, and dynamic resume-prompt generation. It executes natively on the host machine.

### 2.2 The Agentic Engine (LLM Prompt)
A system prompt (`skill.md`) injected into the active AI CLI. It instructs the LLM on how to extract conversational intent and write strictly formatted Markdown files directly to the absolute path provided by the Python CLI.

## 3. Functional Requirements

### 3.1 Storage & Path Resolution
* **FR-1.1:** The system MUST resolve the storage path (`$BASE_DIR`) using a strict cascade:
  1. `$MEMOIR_STORE` (Explicit Environment Variable Override)
  2. Git Root (`<git-root>/.agents/memoir/`)
  3. Global Fallback, only outside Git and only if `$MEMOIR_USE_GLOBAL=true` (`${XDG_CONFIG_HOME:-~/.config}/memoir/memories/{hash}/`, where `{hash}` is the first 8 hex characters of the SHA-256 of `$PWD`)
  4. Current Working Directory (`$PWD/.agents/memoir/`)
* **FR-1.2:** The system MUST maintain two internal directories: `active/` and `archive/`.

### 3.2 CLI Commands (`memoir.py`)
* **FR-2.1 (`init`):** MUST create the required directory structure (`active/` and `archive/`).
* **FR-2.2 (`prompt`):** MUST output a system instruction string containing the exact absolute path to the `active/` directory for immediate LLM ingestion.
* **FR-2.3 (`archive`):** MUST move specified superseded files from `active/` to `archive/`, prepending a `YYYYMMDD-` timestamp to the filename to preserve chronological sorting. With `--superseded`, it MUST archive every active decision named on another active decision's `Supersedes:` line, and MUST be a no-op when there is nothing to archive.
* **FR-2.4 (`resume`):** MUST output the `prompt` instruction (the absolute `active/` path), followed by a copy-paste ready prompt listing the exact absolute paths of all active files, `state-current.md` first, to bootstrap a new LLM session seamlessly.
* **FR-2.5 (`path`):** MUST print the resolved `$BASE_DIR`, for user inspection.

### 3.3 LLM Operations & Commands
* **FR-3.1:** The LLM MUST enforce strict kebab-case naming for all generated files (e.g., `decision-auth-flow.md`).
* **FR-3.2 (`/memoir decision [text]`):** MUST extract explicit architectural choices and write to `active/decision-{slug}.md`, recording the decision, why, rejected alternatives, deferred work, and any superseded decision.
* **FR-3.3 (`/memoir log [text]`):** MUST extract event/milestone logs and write to `active/log-{slug}.md`.
* **FR-3.4 (`/memoir reference [text]`):** MUST record external context/paths to `active/reference-{slug}.md`.
* **FR-3.5 (`/memoir state`):** MUST overwrite `active/state-current.md` using a strict, anti-bloat schema limited to 3 bullets per section:
  * **Goal:** [Current objective]
  * **Completed:** [What was just done]
  * **Blocked/Pending:** [Current errors or open threads]
  * **Next Action:** [The exact next step]
* **FR-3.6 (`/memoir coach`):** MUST evaluate current context drift, identify superseded decisions, and update the state file. On CLEAR, it MUST list the superseded files (for information only) and output two lines the user can paste into the CLI one at a time: `/clear`, then `/memoir reload`. The LLM MUST NOT generate the resume prompt itself.
* **FR-3.7 (`/memoir reload`):** MUST run `memoir.py archive --superseded`, then `memoir.py resume`. It MUST take the active path from the resume output and read every file listed, starting with `state-current.md`. It MUST then reply with the restored Goal and Next Action and wait for the user before acting. If no session is recorded, it MUST say so and start fresh.
* **FR-3.8 (Automatic decisions):** When the user chooses among alternatives or says "decision:" or "let's go with X", the LLM MUST write a decision fragment per FR-3.2 without waiting for `/memoir decision`.

## 4. Non-Functional Requirements

### 4.1 Interoperability
* **NFR-1.1:** The Python CLI MUST run on Python 3.11+ using only standard library modules, or fully encapsulate dependencies using PEP 723 inline metadata for seamless execution via `uv`.
* **NFR-1.2:** The system MUST NOT depend on Model Context Protocol (MCP) servers, background daemons, or specific IDE plugins.

### 4.2 Security & Compliance
* **NFR-2.1:** All state data MUST remain entirely local to the user's filesystem.
* **NFR-2.2:** The system MUST NOT require elevated privileges (sudo/root) to execute or modify state.

### 4.3 Determinism
* **NFR-3.1:** The LLM MUST NEVER guess paths or use relative directories. It MUST rely exclusively on the absolute path dynamically injected by `memoir.py prompt`.

## 5. User Workflow Lifecycle

1. **Initialize:** User runs `memoir.py init` in their project.
2. **Inject Context:** User starts their AI CLI, injecting the absolute path: `claude --append-system-prompt "$(memoir.py prompt)"` (or equivalent).
3. **Develop:** User works normally, issuing `/memoir decision`, `/memoir log`, or `/memoir state` when milestones are reached.
4. **Evaluate:** User issues `/memoir coach`. The LLM recommends a `CLEAR` due to high context density and lists old decisions.
5. **Reload:** 
   * User pastes `/clear`, then `/memoir reload`, into the CLI.
   * Reload archives superseded decisions, loads the active files, and the user continues working with a pristine, focused context window.
   * Fallback for agents without shell access: user runs `memoir.py resume | pbcopy` (or OS equivalent), clears the chat, and pastes the copied prompt.