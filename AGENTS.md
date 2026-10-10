# Agent Guidance

This file is the top-level entry point for agent instructions in this repository. Use progressive disclosure: keep project-wide rules here, and place detailed, scope-specific instructions in the nearest applicable agent guidance file when such files are added. Do not duplicate detailed instructions across files.

## Guidance map

- Read `README.md` for the project purpose and repository-level AI usage statement.
- Read `AI-INTEGRITY-POLICY.md` for the academic-integrity and AI documentation requirements.
- Read `.github/skills/commit-message/SKILL.md` when creating or reviewing commit messages.

## Planning and developer decisions

Agents must enter plan mode before implementing work that requires critical thinking or design, or when there are assumptions or unresolved questions about project requirements, technical design, scope, or behavior. The agent must present a questionnaire with the reasonable possible solutions, trade-offs, and a recommended option where appropriate. The agent must wait for the developer to select an option or provide clarification before implementing that decision.

Do not silently choose among materially different approaches. If new ambiguity or a design decision appears during implementation, pause and return to plan mode with an updated questionnaire.

## AI-assisted work

Follow `AI-INTEGRITY-POLICY.md` for all AI-assisted work. Before pushing AI-assisted changes, developers must understand and review the work, perform meaningful validation, and document the validation results and AI usage in the commit message.