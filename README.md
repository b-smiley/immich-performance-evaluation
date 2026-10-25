# Immich Performance Evaluation

## Project Proposal

This project investigates the performance of Immich, an open-source, self-hosted photo and video management system composed of multiple services deployed through Docker Compose, including a web server, PostgreSQL database, Redis, and a machine-learning container.

The objective is to evaluate how Immich responds to increasing levels of concurrent media uploads. Three workloads will be tested: photo-only uploads, video-only uploads, and a combination of both. By varying the number of simultaneous uploads, the project aims to answer three research questions:

1. How does the number of concurrent uploads affect response time, throughput,
   and error rate?
2. How does workload composition affect performance and capacity?
3. How does resource usage change across Immich's services, and which
   components become bottlenecks?

Testing will be conducted in two phases. Phase 1 will evaluate six factors at a limited number of levels to identify their effects on system performance. Phase 2 will examine the most influential factors in greater detail, with additional testing levels determined by the initial results. Factors that show little impact in phase 1 will not automatically be excluded, as their effects may only become apparent at higher workloads. The results from phase 1 will be used to reassess which factors require further investigation.

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

## Decisions

For design decisions made during the project, see the `/docs` folder.
| title | summary | path |
|-------|---------|------|
| Performance Stack | The performance stack is based on Prometheus and Grafana, with cAdvisor for container metrics. | [performance-stack-decisions.md](/docs/performance-stack-decision.md) |
| Remote Load Generation | Load generation is done on a separate machine to avoid skewing results. This is configured via GitHub Actions and Tailscale.| [remote-load-generation-decision.md](/docs/remote-load-generation-decision.md) |


## AI Usage Statement

This project uses artificial intelligence (AI) to support learning and development. Developers and agents must follow the policy in `./AI-INTEGRITY-POLICY.md`. This explicit policy provides guardrails for responsible AI use and supports academic integrity.

Every commit that uses AI tooling must include an AI Usage statement. The statement must summarize the validation performed, the input prompts and outputs used, and the AI tool, model, version, and usage context. Developers must understand, review, and meaningfully validate AI-assisted work before pushing it. See the [AI Integrity Policy](./AI-INTEGRITY-POLICY.md) and the [commit-message skill](./.github/skills/commit-message/SKILL.md) for details.

## References
[0] - Course Outline SENG 533 – Software Performance Evaluation. University of Calgary - Department of Software Engineering. D2L. Accessed on 2026-10-08. https://d2l.ucalgary.ca/d2l/le/content/771367/viewContent/7792588/View
