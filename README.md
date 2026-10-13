# Immich Performance Evaluation

## Project Proposal

TODO: Add a summary of the project proposal.

## Local Immich setup

The standard Windows onboarding flow runs from **Git Bash**. It checks for Docker
Desktop with Docker Engine `25.0.0` or newer and Docker Compose v2, offers to
install Docker Desktop through `winget` when Docker is missing or too old, and
downloads Immich's current release Compose files.

Review the actions before approving them:

```bash
./provision-windows.sh
```

The `.env` file contains deployment configuration and must be reviewed before starting Immich.
The output directory can be changed with `--directory PATH` or the
`IMMICH_INSTALL_DIR` environment variable.

After reviewing `.env`, start the stack with:

```bash
./run.sh
```

## AI Usage Statement

This project uses artificial intelligence (AI) to support learning and development. Developers and agents must follow the policy in `./AI-INTEGRITY-POLICY.md`. This explicit policy provides guardrails for responsible AI use and supports academic integrity.

Every commit that uses AI tooling must include an AI Usage statement. The statement must summarize the validation performed, the input prompts and outputs used, and the AI tool, model, version, and usage context. Developers must understand, review, and meaningfully validate AI-assisted work before pushing it. See the [AI Integrity Policy](./AI-INTEGRITY-POLICY.md) and the [commit-message skill](./.github/skills/commit-message/SKILL.md) for details.

## References
[0] - Course Outline SENG 533 – Software Performance Evaluation. University of Calgary - Department of Software Engineering. D2L. Accessed on 2026-10-08. https://d2l.ucalgary.ca/d2l/le/content/771367/viewContent/7792588/View
