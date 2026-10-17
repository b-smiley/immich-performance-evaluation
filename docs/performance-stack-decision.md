# Load Generation, Metric Collection, and Dashboard Analysis

## Research and Decision Making Process for Immich Performance Stack

Looking at the official documentation for Immich, it became clear that the metric system to use was Prometheus [1]. Immich already supports this integration so it was a natural choice. Once Prometheus was chosen the next step was to determine how to visualize the metrics collected by Prometheus. Grafana is a common choice for visualizing Prometheus metrics and is also a supported integration by Immich [1]. While this official integration stack provides significant benefits, we still need more metric collection. To get metrics that provide another perspective cAdvisor and Node Exporter can be used to collect container-level metrics and therefore should be sent to the Grafana dashboard as well [2], [3].

Load generation is another important technical decision. To seamlessly integrate into the Grafana dashboard, k6 was chosen as the load generation tool. k6 is a strong recommendation in general for load testing so that plus the fact that it integrates well with Grafana made it a decisive choice [4], [5]. Load generation should be done on a separate machine to avoid skewing the results of the load test. However, for speed of development non-formal test results can be done on the same machine as the Immich host. Additionally the Immich CLI is can be potentially a good option for batching (potentially bulk seeding) [6]. The cloud / local hosting considerations for metric skewing presentation will be discussed in later details.


Keyword Searches Conducted:
- "Immich monitoring Prometheus Grafana telemetry"
- "Grafana k6 file upload"
- "cAdvisor integration with Prometheus"

# AI Usage Statement
- Validation: "Proof reading the content against what I intended to write. Minimal validation required as it is sentence completion and grammar fixes."
- Input prompts: Proper formatting of the AI Usage Statement for this document using the project policy, including the tools used and their versions.
- Output prompts: A sentence completion and grammar fixes incorporated into the document's AI Usage Statement.
- Tool identification: GitHub Copilot CLI, model selected by Auto mode, version 1.0.96, used in this session; VS Code GitHub Copilot inline auto-completion, version not available, used for sentence completion and grammar fixes.

# References

- [1] Monitoring. Immich Documentation. https://docs.immich.app/features/monitoring/
- [2] CAdvisor README. GitHub. https://github.com/google/cadvisor
- [3] Node Exporter README. GitHub. https://github.com/prometheus/node_exporter
- [4] Data Uploads. k6 Documentation. Grafana. https://grafana.com/docs/k6/latest/examples/data-uploads/
- [5] Load Testing Tools: A 2026 Comparison. Asad Abrar. June 22, 2026. Drizz. https://www.drizz.dev/post/load-testing-tools
- [6] The Immich CLI. Immich Documentation. https://docs.immich.app/features/command-line-interface/#commands