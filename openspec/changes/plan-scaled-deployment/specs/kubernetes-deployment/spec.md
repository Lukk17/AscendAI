## Purpose

Defines how the platform is deployed on a Kubernetes cluster for a company: one Helm chart that runs every service with the settings, secrets and health checks of the Compose stack, and scales the busy services automatically.

## ADDED Requirements

### Requirement: One Helm chart deploys the platform, Compose stays for local work

The repository SHALL ship one Helm chart at `deploy/helm/ascend-ai/` that installs the platform on a Kubernetes cluster, with one workload per compose service it runs and every Service named like its compose service. Docker Compose SHALL stay the way to run the stack locally and on a single server, and the chart SHALL NOT change any compose file. Services that exist only for Compose (the TLS gateway, the Ngrok tunnel, the Docker socket metrics exporter and the e2e harness containers) SHALL NOT be rendered by the chart.

#### Scenario: The chart renders without a cluster

- **WHEN** `helm template` renders the chart with its default values and a named Secret
- **THEN** it exits 0 and every rendered resource passes a Kubernetes schema validator in strict mode

#### Scenario: Compose is untouched

- **WHEN** the chart is added to the repository
- **THEN** `compose.yaml`, `compose.ascend-web-hunter.yaml` and the standalone bundle have no change

### Requirement: The busy services scale automatically

`ascend-agent`, `ascend-web-hunter`, `ascend-ocr`, `ascend-audio-scribe` and `ascend-memory` SHALL each have a HorizontalPodAutoscaler on CPU utilization when its autoscaling value is on, which it is by default. Each of their containers SHALL carry a CPU and memory request and limit, the workload SHALL NOT set a fixed replica count while its autoscaler is on, and the minimum, maximum and target values SHALL be chart values that the values schema requires as integers in their valid ranges, with the defaults 1, 5 and 70 percent CPU for each of the five, set per install. A container of the five whose compose service sets no CPU reservation SHALL have the CPU request `250m` by default. Every other service SHALL run the copy count of its chart value, with the copy count of its compose service as the default.

#### Scenario: Load adds copies

- **WHEN** the chart runs on a cluster with the Metrics Server and enough requests reach `ascend-web-hunter` to keep its CPU above the target
- **THEN** the autoscaler raises its copies above the minimum within 5 minutes
- **AND** every new copy becomes ready and answers requests through the `ascend-web-hunter` Service

#### Scenario: A missing autoscaler number is refused

- **WHEN** `helm template` renders the chart with the autoscaler of a busy service on and its maximum not set
- **THEN** it fails with a schema error that names the missing value

### Requirement: Probes use the existing health endpoints

Every workload SHALL have a liveness and a readiness probe on the endpoints its service already serves: `/health` and `/ready` for the four Python services and the sandbox runner, the liveness and readiness health groups on the management port 9918 for the agent, and `/actuator/health` on 9998 for ascend-weather-mcp. A copy whose readiness endpoint answers not ready SHALL receive no traffic and SHALL NOT be restarted for that reason alone.

#### Scenario: A copy that is not ready gets no traffic

- **WHEN** one copy of ascend-ocr answers 503 on `/ready` while another answers 200
- **THEN** the endpoints of the `ascend-ocr` Service list only the ready copy
- **AND** the not ready copy keeps running

### Requirement: Settings come from the configuration reference with the same defaults

Every setting that the configuration reference lists for a service the chart runs SHALL be a chart value of that service, passed to the container under the same environment variable name and with the same default, except the settings that exist only for Compose (published host ports, the bind address and the edge proxy waits). A setting without a default SHALL have none in the chart. A check SHALL compare the chart values with the reference and SHALL fail on a missing setting, a different default or a value with no row in the reference.

#### Scenario: Values and reference agree

- **WHEN** the check runs over the chart values and the configuration reference
- **THEN** it reports no missing setting, no different default and no value without a row

#### Scenario: A changed value reaches the container

- **WHEN** the chart is rendered with one setting of ascend-ocr set to a value other than its default
- **THEN** the rendered ascend-ocr container carries that value under the setting's environment variable name

### Requirement: Secrets come from a Kubernetes Secret the operator creates

The chart SHALL NOT hold or render a secret value. Every secret setting of the configuration reference SHALL reach its container from a Secret whose name the operator gives in a chart value, under the same key name. Rendering or installing without that name SHALL fail with a message that names the missing value.

#### Scenario: No secret name

- **WHEN** `helm template` renders the chart without the Secret name value
- **THEN** it fails with a message that names the value

#### Scenario: No secret value in the rendered manifests

- **WHEN** the chart is rendered with the Secret name set
- **THEN** no rendered resource is a Secret and every secret setting is a reference to a key of the named Secret

### Requirement: The API is routed through a Service and an Ingress, NoVNC reaches the copy that owns the window

The agent's site SHALL be routed by an Ingress to the `ascend-agent` Service, and every other Service SHALL be reachable only inside the cluster unless its Ingress host value is set. The `ascend-web-hunter` Service SHALL spread requests over every ready copy, and the agent SHALL keep the address `http://ascend-web-hunter:7021`. A request under `/novnc/<copy name>/` on the NoVNC host SHALL reach port 7900 of that one copy with the prefix removed and WebSocket upgrades passed through, and every other path or name on that host SHALL answer 404.

#### Scenario: A NoVNC address opens the owner's copy

- **WHEN** two copies of ascend-web-hunter run and a read on copy `ascend-web-hunter-1` answers 428 with a `vnc_url`
- **THEN** the `vnc_url` names `ascend-web-hunter-1` under the NoVNC host
- **AND** opening it reaches the display of `ascend-web-hunter-1`

#### Scenario: Another name is refused

- **WHEN** a request on the NoVNC host asks for `/novnc/ascend-agent/vnc.html`
- **THEN** it answers 404

### Requirement: One sandbox runner per node, used by the agent copies of that node

The sandbox runner SHALL run as one copy on each node that carries the runner label, with the node's Docker socket mounted. Each agent copy SHALL use the runner of its own node, so the runner address that a workspace records names the runner that created it, and agent copies SHALL run only on nodes with a runner while the sandbox is on. Only agent pods SHALL be allowed to reach the runner through the pod network.

#### Scenario: Two labelled nodes run two runners

- **WHEN** the chart runs on a cluster with two nodes carrying the runner label
- **THEN** one runner copy runs on each of them and none on an unlabelled node

#### Scenario: A workspace keeps its runner

- **WHEN** an agent copy on node A creates a workspace and a later call of that workspace comes to an agent copy on node B
- **THEN** the call goes to the runner of node A

### Requirement: Prerequisites are external by default

Keycloak, PostgreSQL, Redis, Qdrant, the object store and the observability back ends SHALL be external prerequisites by default, with their addresses as chart values and their credentials from the operator's Secret. Each of them SHALL have an optional dependency chart, pinned to the latest stable chart version and running the latest stable release of its program, both read at implementation time (owner rule 105.2 of 2026-10-09), and switched by a chart value that is off by default, so that with every switch on the platform runs on its own in a cluster and its services reach those stores with no other value. Before the dependency charts are added, every Compose image of a program that a dependency chart also runs SHALL be raised to that program's latest stable release when it has fallen behind, so Compose and the chart run the same programs (owner answer 106 of 2026-10-09). The Metrics Server and an Ingress controller SHALL be cluster prerequisites that the chart never installs.

#### Scenario: Default install starts no data store

- **WHEN** the chart is rendered with its default values
- **THEN** no rendered workload runs Keycloak, PostgreSQL, Redis, Qdrant, an object store, Prometheus, Grafana, Loki or Tempo

#### Scenario: Dependency charts are pinned

- **WHEN** `Chart.lock` and the chart README are read
- **THEN** every dependency chart has one exact version
- **AND** the README names, for each, the program version it runs and the date both were read
- **AND** where Compose runs the same program, its Compose image names the same program version

#### Scenario: Every dependency chart on runs the stack on its own

- **WHEN** the chart is installed on a kind cluster with every dependency chart switched on
- **THEN** every pod becomes ready
- **AND** every enabled service answers its readiness endpoint with ready

### Requirement: Pods run with a restricted security context and default-deny networking

Every pod SHALL run as a non-root user with privilege escalation off and every capability dropped, except where the chart documentation names an exception and its reason. The namespace SHALL have a default-deny NetworkPolicy and one allow policy per component for the calls that component makes.

#### Scenario: A rendered pod is restricted

- **WHEN** the chart is rendered with its default values
- **THEN** every pod that is not a documented exception has `runAsNonRoot` true, `allowPrivilegeEscalation` false and every capability dropped
- **AND** a NetworkPolicy that selects every pod and allows nothing is rendered

### Requirement: The chart is documented and tested

`docs/DEPLOYMENT.md` SHALL have a section for Kubernetes, and the chart SHALL have a README that lists every value with its default, every Secret key, the cluster prerequisites and the documented exceptions. `helm lint`, `helm template` with a strict schema check one install on a local kind cluster with a load step that proves a scale-up, and one install on kind with every dependency chart switched on SHALL pass before the change is done.

#### Scenario: The kind run proves scaling

- **WHEN** the kind run of the change installs the chart and starts its load step
- **THEN** the ascend-web-hunter autoscaler shows 2 or more copies within 5 minutes
- **AND** the run record holds the commands, their output and the cluster deletion at the end
