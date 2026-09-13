---
name: git-commit
description: |
  Execute `git commit` with conventional commit message analysis, intelligent
  staging, and message generation. Use when using `git` to commit changes,
  editing commits, rebasing, or when the user mentions "/commit".

  Supports:
  (1) Auto-detecting type and scope from changes,
  (2) Enforcing atomic, build-passing commits and bisection integrity,
  (3) Generating conventional commit messages from diffs,
  (4) Interactive commit with optional overrides and fixup targeting,
  (5) Intelligent file staging for logical grouping
---

# Git Commit Rules

Create standardized, semantic Git commits following the Conventional Commits specification. Inspect project guidelines, stage files logically, and construct high-context commit messages while maintaining atomic, build-passing commits (an always-green history) and preserving bisection integrity.

## Precedence & Hierarchy

Resolve rule conflicts using the following cascading hierarchy:

1. **Defer to Project Guidelines (Override)**: Inspect and respect repository-specific conventions (e.g., `CONTRIBUTING.md`, `.github/COMMIT_CONVENTIONS.md`, `.commitlintrc`, or active Git hooks). Yield to project rules whenever a direct conflict exists (e.g., requiring capitalized subject lines or custom ticket prefixes).
2. **Apply This Specification as Baseline (Additive)**: Use this specification in full when no project rules exist. Where project guidelines are vague, incomplete, or silent (e.g., stating "use conventional commits" without defining body depth, scratchpad reasoning, line wrapping, or staging guardrails), treat this document as an additive baseline to enforce high quality.

## Core Pillars

Satisfy three core pillars for every commit generated:

1. **Enforce Conventional Semantics**: Structure every commit header as `<type>[scope]: <description>` to provide standardized, machine-readable metadata for automated changelogs and release tooling.
2. **Articulate High-Context Intent**: Capture an Architectural Decision Record (ADR) mindset in the body by explaining root cause, intent, and implementation trade-offs.
3. **Preserve Build Stability & Bisection Integrity**: Ensure every commit is atomic and build-passing, leaving the repository in a testable state so that debugging operations (such as `git bisect`) remain deterministic.

## Conventional Commit Format

```text
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

### Formatting Rules

- **Limit Header Length**: Ensure the full header (`<type>[scope]: <description>`) **SHOULD** be 50 characters or less and **MUST NOT** exceed 72 characters.
- **Enforce Lowercase Imperative Subject**: Write the description in lowercase, present tense, and imperative mood (e.g., "add", not "added" or "adds").
- **Omit Trailing Period**: Do not end the subject line with a period.

## Commit Types & Automated Release Mapping

| Type       | Purpose                                                         | Release Mapping (e.g., SemVer) |
| :---       | :---                                                            | :---                           |
| `feat`     | New feature for the user                                        | `MINOR` bump                   |
| `fix`      | Bug fix for the user                                            | `PATCH` bump                   |
| `docs`     | Documentation changes only                                      | No version bump                |
| `style`    | Formatting or style changes (no production logic impact)        | No version bump                |
| `refactor` | Code restructuring without changing behavior or adding features | No version bump                |
| `perf`     | Performance improvement                                         | `PATCH` bump                   |
| `test`     | Adding or updating tests                                        | No version bump                |
| `build`    | Build system or external dependency updates                     | `PATCH` bump                   |
| `ci`       | CI configuration files and scripts                              | No version bump                |
| `chore`    | Maintenance tasks and miscellaneous updates                     | No version bump                |
| `revert`   | Reverting a previous commit                                     | `PATCH` bump                   |

## Breaking Changes

Indicate breaking changes (which trigger a `MAJOR` version bump in release tooling) using a `!` after the type/scope and a `BREAKING-CHANGE:` footer in Git trailer form.

```text
# Breaking change via header indicator (triggers MAJOR bump)
feat(api)!: remove deprecated v1 endpoint

# Breaking change via footer (triggers MAJOR bump)
feat(config): allow extended configurations

BREAKING-CHANGE: The `extends` key now overrides default values instead of merging them.
```

## Workflow

### Step 1: Check Project Rules & Analyze Diff

Inspect repository configuration and working tree changes:

```bash
# 1. Check for project commit guidelines or commitlint configs
ls -a CONTRIBUTING* .github/COMMIT* .commitlint* commitlint.config* 2>/dev/null

# 2. Inspect staged and unstaged changes
git diff --staged
git diff
git status --porcelain
```

Reconcile any discovered project rules with this guide according to the **Precedence & Hierarchy** section. Verify that working tree changes maintain a passing build state before staging.

### Step 2: Stage Files Intelligently (Single Responsibility Principle)

Apply the Single Responsibility Principle (SRP) to form atomic, logically isolated commits:

```bash
# Stage specific files
git add path/to/file1 path/to/file2

# Stage by pattern
git add *.test.* src/components/*

# Interactive patch/hunk-level staging
git add -p
```

> **Staging Guardrails:**
> - **Avoid Bulk Staging**: Never use `git add .`, `git add -A`, or `git commit -a`. Stage files explicitly at the hunk or file level.
> - **Prevent Secret Exposure**: Never stage secrets, credentials, or environment files (`.env`, `*.pem`, `credentials.json`).

### Step 3: Generate Commit Message

#### Analysis Scratchpad (Chain of Thought)

Execute an explicit step-by-step analysis in a scratchpad or internal reasoning block before drafting the commit message:

1. **Perform Root Cause Analysis (RCA)**: Identify the core problem, feature requirement, or architectural trigger prompting this change. (Do not simply restate what lines changed).
2. **Formulate Architectural Decision Rationale (ADR)**: Justify why this specific implementation, pattern, or refactoring path was selected over alternative approaches.
3. **Calibrate Body Depth**:
   - **Trivial/Mechanical Changes**: Limit the body to 1–2 concise sentences or omit if the header is completely self-explanatory.
   - **Complex Changes & Refactors**: Structure a multi-paragraph or bulleted breakdown detailing the prior system state, the architectural shift, and any non-obvious side effects or assumptions.

#### Message Construction

Synthesize the analysis from your scratchpad into the final commit message structure:

- **Type**: Select the exact change category from the Commit Types table.
- **Scope**: Identify the affected module, package, or component in lowercase parentheses (optional).
- **Description**: Write a concise, imperative summary of the change (<=50 characters target, 72 characters max). Do not capitalize the first letter. Do not end with a period.
- **Body**: Transcribe the RCA intent and ADR implementation rationale derived during analysis into the commit body.

#### Style & Syntax Rules

- **Use Imperative Voice**: Write the description and body in the present tense and imperative mood ("add feature", not "added feature" or "adds feature").
- **Apply Markdown Formatting**: Use rich Markdown inside the body (backticks for symbols/files, bullet lists for multi-part changes, and reference links where appropriate).
- **Enforce Line Wrapping**: Wrap lines in the commit body at hard 72-character limits.

### Step 4: Execute Commit & Verify Passing Build Gate

Apply the generated message to the repository and handle pre-commit hook results:

```bash
# Standard single-line commit
git commit -m "<type>[scope]: <description>"

# Multi-line commit with body and footers
git commit -m "$(cat <<'EOF'
<type>[scope]: <description>

<body describing motivation and context>

<footer or trailers>
EOF
)"

# Targeted fixup commit for an existing commit in history
git commit --fixup <commit-hash>
```

#### Pre-Commit Hook Failure Recovery Loop

Handle pre-commit hook failures using the following sequence:

1. **Stage Auto-Formatted Changes**: If the hook auto-formatted or modified files in the working tree, stage those formatted changes (`git add <file>`) and rerun the exact same commit command.
2. **Fix Code Failures First**: If the hook failed due to syntax errors, broken tests, or linter violations, **FIX THE CODE FIRST**. Stage the fixes and re-execute the commit once tests pass.
3. **Never Bypass Hooks**: Do NOT pass `--no-verify` or `-n` to force a broken commit into history.

## Best Practices

- **Enforce Atomic Commits**: Ensure each commit reflects a Single Responsibility Principle (SRP) boundary containing exactly one logical change.
- **Separate Concerns**: Never mix refactoring, formatting fixes, and functional behavior changes in the same commit.
- **Commit Incrementally**: Commit changes immediately upon completing a sub-task rather than waiting until the entire task is finished.
- **Verify Locally**: Run relevant local tests for the specific change prior to executing each commit.

## Git Trailers

Append standardized metadata footers for tracking, review, and issue integration:

| Trailer Key             | Purpose                                          |
| :---                    | :---                                             |
| `Signed-off-by:`        | Certifies Developer Certificate of Origin (DCO)  |
| `Assisted-by:`          | Credits secondary contributors or AI assistance  |
| `Co-authored-by:`       | Credits co-authors on a commit                   |
| `Suggested-by:`         | Credits the person who suggested the change      |
| `Reviewed-by:`          | Identifies peer reviewers who approved the code  |
| `Acked-by:`             | Indicates subsystem maintainer approval          |
| `Tested-by:`            | Credits the individual who validated testing     |
| `Reported-by:`          | Credits the reporter of a bug                    |
| `Fixes:`                | References the commit hash that introduced a bug |
| `Closes:` / `Resolves:` | Automatically closes an issue or PR upon merge   |
| `Refs:` / `Relates-to:` | References an issue or PR without closing it     |

> Refer to `git-interpret-trailers(1)` for additional documentation.

## History Integrity & Safety Protocol

### Build Health & Bisection Integrity

- **Maintain Continuous Build Health**: Ensure every commit added to the branch leaves the repository in a fully passing state to preserve `git bisect` efficacy and keep the branch deployment-ready.
- **Use Fixups for Historical Amendments**: Generate a standard fixup commit using `git commit --fixup <commit-hash>` when modifying prior work on the current branch. Keep historical amendments explicit without rewriting history on the fly.

### Non-Destructive Operations & Guardrails

- **Prohibit Automatic History Rewriting**: NEVER run interactive rebases (`git rebase -i`), autosquash executions (`git rebase --autosquash`), or history rewrites automatically. Prepare `--fixup` commits, but require explicit user authorization before rebasing.
- **Prohibit Unauthorized Force Pushing**: NEVER run `git push --force` or `--force-with-lease` without explicit user confirmation.
- **Prohibit Global Config Mutation**: NEVER modify global or local Git configuration without explicit permission.
- **Respect Git Hooks**: NEVER pass `--no-verify` to bypass pre-commit or commit-msg hooks unless explicitly instructed by the user.
