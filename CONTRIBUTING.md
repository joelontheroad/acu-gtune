# Contributing Guide

Thank you for contributing to this project! To maintain high engineering, security, and privacy standards across all our utilities, all contributions must adhere to the following guidelines.

---

## Code of Conduct & Standards Alignment

All code in this repository adheres to the standards defined in the project's `STANDARDS.md` and `AGENTS.md`.

### Key Directives:
1. **SPDX Headers**: Every new source file must begin with the standard SPDX header:
   ```text
   // SPDX-FileCopyrightText: 2026 [Author/Organization]
   // SPDX-License-Identifier: AGPL-3.0-or-later
   ```
2. **Privacy**: Zero telemetry, no external phone-home requests, local storage only (`~/.config/<tool>`).
3. **Security**:
   - Local web servers must bind strictly to `127.0.0.1`.
   - Never use `yaml.load()` (always use `yaml.safe_load()`).
   - Never use `shell=True` or `exec()` for shell invocations.
   - Canonicalize paths using `realpath` to prevent path traversal (CWE-22).
   - Set POSIX directory permissions to `0700` and config file permissions to `0600`.
4. **Portability**: All file operations must explicitly declare `encoding="utf-8"`.

---

## Commit Message Guidelines

We follow **Conventional Commits 1.0.0**:

- `feat:` A new user-facing feature or CLI flag.
- `fix:` A bug fix.
- `docs:` Documentation updates only.
- `style:` Code style, formatting, or linting without behavioral changes.
- `refactor:` Code restructuring that neither fixes a bug nor adds a feature.
- `perf:` Performance improvements.
- `test:` Adding or updating unit/CLI tests.
- `chore:` Dependency bumps, CI updates, or build tooling.

**Example**:
```text
feat(cli): add --json flag for machine-readable output
```

---

## Development Workflow

1. **Fork & Branch**: Create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-new-feature
   ```
2. **Make Changes**: Ensure all new files have SPDX headers and tests.
3. **Run Tests & Linter**:
   - Python: `pytest` and `ruff check .`
   - Node: `npm test` and `npm run lint`
4. **Update Documentation**:
   - Update `README.md` if flags or configuration change.
   - Add an entry under `[Unreleased]` in `CHANGELOG.md`.
5. **Submit a Pull Request**: Ensure CI checks pass cleanly.
