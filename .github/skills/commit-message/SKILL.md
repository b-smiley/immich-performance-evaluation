---
name: commit-message
description: Stage the intended project changes and create or review commit messages from the complete staged diff using Conventional Commits, cohesive body bulletins, and transparent AI usage documentation.
---

# Commit Message Skill

Use this skill when creating or reviewing a commit message for this project.

## Workflow

Before generating a commit message:

1. Inspect the working tree and index with `git status --short`, `git diff`, and `git diff --cached`.
2. Identify every file that belongs to the intended commit, including modified, deleted, renamed, and untracked files.
3. Stage the complete intended file set with `git add -- <paths>`. Do not stage unrelated files. If a file contains both related and unrelated changes, stop and ask the developer how to separate them instead of staging the entire file.
4. Confirm the staged scope with `git status --short` and review the complete staged patch with `git diff --cached --stat` and `git diff --cached`.
5. Generate the commit message from the complete `git diff --cached` output. Do not base the message only on `git diff`, `git diff --stat`, newly added files, or the latest edit.

The commit message must account for all staged additions, modifications, deletions, renames, and content changes. If the staged diff is empty, or if the intended commit scope is unclear, do not generate a final message; ask the developer for clarification.

## Title

Use the Conventional Commits format:

```text
<type>[optional scope]: <short imperative description>
```

Choose a type that accurately describes the change, such as `feat`, `fix`, `docs`, `refactor`, `test`, `build`, `ci`, or `chore`. Keep the title concise, specific, and human-readable. Use a scope when it adds useful context.

## Body

After a blank line, use brief bulletins. Each bulletin must summarize one cohesive change, rather than listing unrelated implementation details.

```text
- <cohesive change>
- <cohesive change>
```

## AI Usage statement

If AI tooling contributed to the commit, add an `AI Usage:` section after the body. Use labeled, concise entries and do not include full prompt or output transcripts:

```text
AI Usage:
- Validation: "<exact validation statement supplied by the developer>"
- Input prompts: <brief summary of the prompts or instructions provided>
- Output prompts: <brief summary of the AI-generated outputs used or adapted>
- Tool identification: <AI tool, model, version, and usage context, such as Copilot CLI or web>
```

The `Validation` entry must be supplied by the developer in their exact wording. The agent must not write, rewrite, summarize, infer, or verify the developer's validation statement, and must not substitute agent-run checks for it. Ask the developer to provide the exact statement if it is missing. Preserve the supplied wording verbatim, including its quotation marks if provided.

The developer's statement must describe meaningful validation they performed, not merely a superficial inspection. Developers must understand and review AI-assisted work and complete validation before pushing it. Do not finalize an AI-assisted commit message until the developer has supplied this exact statement.

If AI did not contribute to the commit, omit the `AI Usage:` section. Follow `AI-INTEGRITY-POLICY.md` for the full project requirements.
