# Remote Load Generation

## Scope and Goal

Configuring the load generation and service under test to run on a separate hardware so that the results are not skewed by the load generators resource usage.

## Financial Risk and Maintenance for a University Project

As this is a university project, there are some constraints that need to be taken into account. We wanted to avoid the inherit risks of accidental Virtual Machine overcharge from a provider. This is a common occurrence where developers get extremely high credit card charges due to improperly configured machines, DDOS attacks, or other blindspots of making a production ready system. Since this project is not a project-ready repository but a university research project, the risk of getting charged for high usage is a risk that this team was not willing to take. There were some options online that allow no credit card signup but their hardware options and configurability are limited.

## Alternative Solutions - Full Local Setup

We considered using a developer 1 laptop client connecting to developer 2 laptop Immich host via a local network but the public university networks typically block this type of traffic. Additionally, a fully local system does not test the network latency that would be present in a real-world scenario. Finally a multiple machine local-only setup requires multiple researchers to be present and we wanted a more ephemeral setup that could be run by a single researcher.

## Alternative Solutions - Cloud Providers

Some cloud providers like Oracle Cloud [2] and Amazon Web Services [3] were considered as cloud providers but they (to my knowledge and research, and at the time of this writing) require a credit card for signup.

## Solution - Tailscale and GitHub Actions

We decided to use a ephemeral and reproducible setup using Tailscale [0] and GitHub Actions. The Immich host and monitoring stack will run on a x86 GitHub-hosted runner while the k6 load generator will run on a separate ARM GitHub-hosted runner. The two runners will be connected via Tailscale so that the k6 load generator can connect to the Immich host.

With GitHub Actions we must be cautious that the VMs are not running on the same physical hardware despite being a VM. This can only happen if the runners are on the same CPU architecture. Therefore, we have configured the runners to be on different CPU architectures which ensures different physical hardware. The k6 load generator runner and the Immich runner both output metrics artifacts into "client" and "server" artifacts respectively. The artifacts are then downloaded and replayed on a local machine for analysis. Further visualization a design will be coming on how to aggregate the metrics from multiple samplings and factors but for now this is a simple overview of the outputs from the remote load generation setup.

The Tailscale connection is ephemeral and will be torn down after the workflow completes. It creates a handshake connection between the two runners and allows the k6 load generator to connect to the Immich host. Specific feasibility tests are done before a full load test to ensure that the Tailscale network connection itself is not a bottleneck. In general we noticed that the connection is typically direct which is preferred. Each feasibility workflow will output the Tailscale network metrics to help determine if the connection is direct or relayed, how much latency is added, and how much throughput is available. Confirming these metrics is a important step to ensure that the network itself is not the bottleneck for the load test. We found that in general there is excellent throughput and low latency between the two runners (no more than what a real network would have).

The Immich docker host itself needs a empheral admin account in order to run the load test. The workflow will create a new admin account and API key via the Immich API endpoints [1]. The account is deleted after the workflow completes.

# AI Usage Statement

- Validation: Validated against 3rd party documentation, previous experience with AWS, Heroku, and other cloud providers (they are never free), and built out a PoC see commit for more validation details.
- Input prompts: Told copilot agent to create a PoC for this pre-decided load generation and monitoring stack design. Gave the agent a prompt outline similar content to what this document summarizes.
- Output prompts: Outputted a PoC Pull Request (scripts, code-gen) that proved the design and architecture of the remote load generation was possible and feasible for metric capture. Outputted auto-completion suggestions for this document to summarize the PoC and design decisions.
- Tool identification: GitHub Copilot CLI, model selected by Auto mode, version 1.0.96, used to create PoC scripts; VS Code GitHub Copilot inline auto-completion, version not available, used for sentence completion and grammar fixes within this document.

# References

- [0] Tailscale Github Action. Jan 30, 2026. Tailscale Documentation. https://tailscale.com/docs/integrations/github/github-action
- [1] API Endpoints. Immich Documentation. https://api.immich.app/endpoints/api-keys
- [2] Oracle Cloud Free Tier. Oracle. https://www.oracle.com/ca-en/cloud/free/
- [3] AWS Free Tier.Amazon Web Services (AWS). https://aws.amazon.com/free/
