---
name: code-review
description: "Structured multi-stage code review for the Koma project. Use when: reviewing a diff, PR, branch, or changed files; checking for bugs, type issues, missing tests, style violations, or security risks before committing/merging. Produces a structured review report with severity-ranked findings and a conventional-commits message draft."
argument-hint: "optional: file paths, 'last commit', 'branch <name>', or 'unstaged'"
user-invocable: true
---

# Code Review (Koma)

Multi-stage review workflow for this Python project (uv + src layout + ruff + pytest-cov + Pylance).
Produces a structured report: **blocker / warning / nit**, each with file:line, issue, and suggested fix.

## When to Use

- Reviewing a diff (unstaged, staged, a commit, or a branch) before committing or merging
- Reviewing specific files after a feature implementation
- Auditing a change for correctness, types, test coverage, style, or security

## Inputs

Resolve the review scope first. If the argument is empty, default to `git diff HEAD` (unstaged + staged).

| Argument | Scope command |
|---|---|
| (none) | `git diff HEAD` |
| `unstaged` | `git diff` |
| `staged` | `git diff --cached` |
| `last commit` | `git diff HEAD~1 HEAD` |
| `branch <name>` | `git diff <name>...HEAD` |
| file paths | review those files in full |

## Procedure

### 1. Establish scope
1. Run the scope command from the inputs table above.
2. List changed files and classify each: `src/koma/core/*` (business logic), `src/koma/ui/*` (Tkinter UI), `tests/*`, config/build files.
3. If no changes exist, report that and stop.

### 2. Static analysis (machine checks first)
Run in order; capture output, do not fix anything yet:
1. `uv run ruff check <changed files or .>` — lint (E, W, F, I, B, C4, UP, N, SIM, RUF, T20)
2. `uv run ruff format --check <files>` — formatting drift
3. Pylance diagnostics for each changed Python file via `mcp_pylance_mcp_s_pylanceLSP` with method `textDocument/diagnostic` and `{ textDocument: { uri: "file:///..." } }`. Read each `Diagnostic.code` (e.g. `reportArgumentType`, `reportOptionalMemberAccess`) before judging severity.
4. If a signature changed, verify call sites with `mcp_pylance_mcp_s_pylanceCheckSignatureCompatibility`.

### 3. Tests and coverage
1. Run `uv run pytest` (addopts already include `--cov=koma` with term-missing + html report).
2. For each changed module, check the coverage report line: new/modified lines without coverage are a **warning** unless intentionally untestable (UI glue, entry points — `main.py`, `utils.py`, `ui/*` are omitted from coverage by design, do not flag them).
3. Check `tests/` for a corresponding test file per changed module (`core/archive.py` → `tests/test_archive.py`). Missing test for new behavior = **warning**.
4. If a test fails, attribute it: pre-existing failure vs. introduced by this diff.

### 4. Manual review per focus area
Review the diff line-by-line against each area. This project processes user file paths, archives, and images on Windows — pay extra attention to:

- **Correctness / bugs**
  - Edge cases: empty dirs, zero-size images, missing files, duplicate names, Unicode/long Windows paths, non-ASCII filenames (test data contains CJK names)
  - Exception handling: broad `except` swallowing errors; partial state on failure (e.g. half-renamed files, half-extracted archives)
  - Off-by-one in page/slice indexing; `natsort` vs `sorted` ordering assumptions
  - Resource leaks: unclosed file handles, `cv2`/`PIL` images, subprocess handles
- **Types & static analysis**
  - Missing/incorrect annotations on public functions; `Optional` receivers dereferenced without narrowing
  - Any Pylance diagnostics from step 2 that are not false positives
- **Test coverage**
  - New branches (if/except) without test cases; mocked vs. real filesystem boundaries
- **Style & readability**
  - Naming consistent with existing modules (snake_case, module responsibilities match `core/` layout)
  - Duplicated logic that should move to `utils.py`
  - `print` in library code (RUF T20) — should use the project logger
- **Security & dependencies**
  - Path handling: no unvalidated user input reaching `os.remove`/`shutil`/`send2trash` (path traversal)
  - Archive extraction: zip-slip style issues (`..` in member names)
  - New dependencies: are they in `pyproject.toml` and `uv.lock`? heavy deps (onnx, opencv) imported lazily?

### 5. Produce the report
Report body is written in **中文** (code, file paths, symbols, and tool output stay as-is). Omit empty sections.

```markdown
## 代码评审: <scope>
文件: <n> 个变更 (+<a>/-<d>)

### 阻断问题（合并前必须修复）
- `src/koma/core/foo.py:42` — <问题描述>。修复建议: <suggestion>

### 警告（建议修复）
- ...

### 小建议（可选）
- ...

### 检查结果
- ruff: <通过/失败, n 个问题>
- Pylance: <通过/失败, n 个问题>
- pytest: <通过/失败, n 个测试> | 变更行覆盖率: <n/n>

### 结论
<同意合并 | 要求修改> — 一句话理由

### Commit Message 草稿
<type>(<scope>): <subject>

- <变更点 1>
- <变更点 2>
```

### 6. Draft the commit message
Derive the draft from the diff and the verdict above:
1. **Type** from the dominant change: `feat` (new behavior), `fix` (bug fix), `refactor` (restructure, no behavior change), `test` (tests only), `docs`, `chore` (build/deps/config), `perf`.
2. **Scope**: the main module touched (e.g. `converter`, `scanner`, `ui`); omit it when the change spans many modules.
3. **Subject**: 中文, imperative, ≤ 72 字符, 结尾无句号.
4. **Body**: 1–5 条要点，说明改了什么/为什么，必要时引用关键文件。
5. The draft must satisfy conventional commits so it passes `cz check` (the commitizen pre-commit hook).
6. If any blocker remains, mark the draft provisional (e.g. prefix the body with `注: 存在阻断问题，修复后再提交`).

## Severity Rules

| Level | Criteria |
|---|---|
| Blocker | Crash, data loss/corruption (this tool mutates user files!), path traversal, failing test caused by diff, Pylance error-level diagnostic |
| Warning | Uncovered new branch, missing test for new behavior, swallowed exception, type narrowing gap, formatting drift |
| Nit | Naming, micro-style, docstring gaps |

**Project-specific hard rule:** any change that deletes, renames, moves, or overwrites user files must be reviewed for the failure path (what partial state remains if it crashes mid-operation). Treat data-loss risk as a blocker.

## Completion Criteria

- All five stages executed (scope, static, tests, manual, commit-message draft)
- Report emitted in the format above with a verdict and a conventional-commits message draft
- No code was modified — review only. If the user then asks to fix findings, apply fixes and re-run stages 2–3 to verify.
