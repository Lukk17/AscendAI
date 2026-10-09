# Plan Scaled Deployment

## Why

Every service of the platform is now safe with several containers of itself (owner answer 87 of 2026-10-08), but the only deployment the repository ships is Docker Compose: one container of each service, on one machine, with no automatic scaling. A company deployment needs the busy services to grow and shrink with load across several machines, with the same settings, the same secrets and the same health checks the Compose stack already has. Owner answer 99.1 of 2026-10-09 asks for that as a Kubernetes Helm chart.

Build order (owner build order of 2026-10-04, which supersedes the earlier orders, and the order decision of 2026-10-09 for owner answer 99.1): build group 5 (company), position 9, directly before `update-docs-and-architecture`, which moves to position 10 and documents this change too. It needs every change before it, because the chart deploys the services those changes build with the settings they define: in particular `fix-linux-docker-host-access` (the configuration reference `docs/CONFIGURATION.md`), `scale-web-hunter-across-containers` and `scale-ocr-and-audio-across-containers` (the services that run as several copies), `harden-cloud-deployment` (the production posture the chart keeps), `add-keycloak-login` (the issuer and the service token), `add-deployment-modules` (the module list), `add-agent-sandbox` (the sandbox runner) and `add-customer-stack-installer` (the data stores of a customer stack). No change of build groups 1 to 4 depends on it: they name it only as company work that plans the scaled deployment later.

## What Changes

- A Helm chart `deploy/helm/ascend-ai/` (chart `apiVersion: v2`) for company deployments of the whole platform. Docker Compose stays the way to run the stack locally and on a single server.
- One Kubernetes workload per compose service the chart runs. A Horizontal Pod Autoscaler (`autoscaling/v2`, CPU utilization) for the five services that can get busy: `ascend-agent`, `ascend-web-hunter`, `ascend-ocr`, `ascend-audio-scribe` and `ascend-memory`. The other services run a fixed number of copies from a chart value.
- Liveness and readiness probes from the endpoints the services already have: `/health` and `/ready` of the Python services and of the sandbox runner, and the Spring Boot health groups on the management port of the agent.
- Every setting of the configuration reference (`docs/CONFIGURATION.md` and the four per-service references) is a chart value with the same default, passed to the container under the same environment variable name. A setting with no default stays without one.
- Every secret comes from a Kubernetes Secret that the operator creates. The chart only references it and never holds a secret value.
- The role of the web-hunter edge proxy is taken by a Kubernetes Service and an Ingress for the API. The NoVNC part, which routes `/novnc/<pod name>/` to one copy, cannot be expressed by an Ingress, so a small NoVNC router (the Caddy image of the edge proxy with a chart-owned Caddyfile) stays for that path only, and ascend-web-hunter runs as a StatefulSet so each copy has a fixed name (design D6, confirmed by owner answer 103.4 of 2026-10-09).
- The sandbox runner runs as one copy per node (a DaemonSet), on the nodes the operator marks for it, and each agent copy uses the runner of its own node.
- Keycloak, PostgreSQL, Redis, Qdrant, the object store and the observability back ends (Prometheus, Grafana, Loki, Tempo) are external prerequisites by default, each with its address in a chart value. Each one can instead be installed from a dependency chart, pinned by version and switched by a chart value that is off by default, because a company usually brings its own database (owner answer 103.3 of 2026-10-09). With every switch on, the stack runs on its own in a cluster. The chosen charts and their sources are in design D9. The CloudPirates charts for PostgreSQL, Redis and Keycloak are accepted (owner answer 105.1 of 2026-10-09). Every dependency chart and the program it runs use their own latest stable versions, read and pinned at implementation time, and the Compose monitoring stack moves to the same versions in `add-observability`, so Compose and the chart run the same programs (owner rule 105.2 of 2026-10-09). When this change is built, its first chart step raises any Compose image of those programs that has fallen behind by then to the latest stable release too (owner answer 106 of 2026-10-09).
- The autoscaler defaults of each busy service are chart values set per install, so each company customer, which has its own install, sets its own: at least 1 copy, at most 5, scale above 70 percent CPU, and a CPU request of `250m` where compose sets no CPU reservation (owner answer 103.2 of 2026-10-09).
- Tests: `helm lint`, `helm template` checked with a Kubernetes schema validator, one install on a local kind cluster where a load step proves that the autoscaler adds copies, and one install on kind with every dependency chart switched on.
- Documentation: a Kubernetes section in `docs/DEPLOYMENT.md`, and every chart value with its default in the chart README.

## Capabilities

### New Capabilities

- `kubernetes-deployment`: the Helm chart, its workloads, autoscaling, probes, configuration values, secrets, routing of the API and of NoVNC, the sandbox runner per node, the prerequisites, and the tests and documents that prove it.

### Modified Capabilities

None. The Compose deployment and its capabilities (`production-deployment` of `harden-cloud-deployment`, `ascend-agent-containerization`) keep their requirements unchanged.

## Impact

- New: `deploy/helm/ascend-ai/` (`Chart.yaml`, `values.yaml`, `values.schema.json`, `templates/`, `files/novnc-router.Caddyfile`, `Chart.lock`, `ci/kind-values.yaml`, `ci/kind-redis.yaml`, `ci/kind-all-dependencies-values.yaml`, `README.md`) and the check script `deploy/helm/scripts/check_values_match_reference.py`.
- Changed documents: `docs/DEPLOYMENT.md` (new section "Kubernetes"), the root `README.md` documentation map, `docs/CONFIGURATION.md` (one sentence that the chart reads the same settings), the root `AGENTS.md` (one paragraph on the chart).
- No service code, no compose file, no API, no stored data changes. No new setting of a service: every chart value maps to a setting that exists.
- No CI workflow is added. The checks run locally from the commands of the tasks.

## Relevant Skills

- `deployment-patterns` for the Kubernetes workloads, probes, Horizontal Pod Autoscaler, PodDisruptionBudget, NetworkPolicy and Helm chart standards
- `docker-patterns` for the images the chart runs, the sandbox runner's Docker socket and the pinned image digests
- `springboot-patterns` for the agent's health groups and its settings as environment variables
- `python-patterns` for the settings of the four Python services the chart passes
- `coding-standards` for the check script
- `security-review` for the Secret handling, the NetworkPolicies and the sandbox runner's node access
- `markdown-writer` for `docs/DEPLOYMENT.md` and the chart README
