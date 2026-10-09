## Purpose

A separate small service that creates, runs commands in, reads and writes files in, and destroys throwaway sandbox containers called workspaces. It is the only component allowed to start sandbox containers, so the agent never holds the container engine's socket. Each workspace is isolated from the agent, its secrets, other tenants, internal services and the host, has hard resource, time and network limits, and is removed even when the agent or the runner crashes.

## ADDED Requirements

### Requirement: The runner is the only component that controls sandbox containers

The sandbox runner SHALL be a service of its own, separate from the agent. It SHALL be the only service that creates, starts, stops or removes sandbox containers and their networks. The agent container SHALL NOT have the container engine's socket mounted and SHALL NOT reach the engine API by any other route. The runner SHALL NOT publish any port on the host, and SHALL be reachable only on the stack's private network, which no workspace ever joins. One runner SHALL run per container engine host, shared by every agent copy on that host, and it SHALL list and remove only the objects of its own engine.

#### Scenario: The agent has no engine socket

- **WHEN** the stack is started from `compose.yaml`
- **THEN** the `ascend-agent` container has no mount of the container engine socket
- **AND** the `ascend-sandbox-runner` container is the only service with that mount for sandbox work

#### Scenario: The runner is not reachable from the host network

- **WHEN** a client on the host connects to the runner's port on any host address
- **THEN** the connection is refused because no host port is published

#### Scenario: A workspace cannot reach the runner

- **WHEN** a command inside a workspace tries to connect to the runner by its service name or address
- **THEN** the connection fails

### Requirement: Every runner call is authenticated and scoped to one tenant

Every call to the runner API except the health and readiness endpoints SHALL carry a bearer token equal to the configured runner token and a tenant id header. The runner SHALL refuse to start when the token is missing or shorter than 32 characters. A call without a valid token SHALL be answered 401. A call without a tenant id, or with a tenant id that is not a lowercase slug of 1 to 64 characters of letters, digits and hyphens, SHALL be answered 400. A workspace SHALL belong to the tenant that created it, and every call naming a workspace of another tenant SHALL be answered 404, exactly as for a workspace that does not exist. Listing SHALL return only the calling tenant's workspaces.

#### Scenario: Missing token

- **WHEN** a client calls the create endpoint without a bearer token
- **THEN** the answer is 401 with an RFC 7807 problem body
- **AND** no container is created

#### Scenario: Another tenant's workspace

- **WHEN** tenant `b` runs a command in a workspace created by tenant `a`
- **THEN** the answer is 404
- **AND** the body does not reveal that the workspace exists

#### Scenario: Listing is per tenant

- **WHEN** tenants `a` and `b` each have one workspace and tenant `a` lists workspaces
- **THEN** only tenant `a`'s workspace is returned

### Requirement: The runner API covers the whole workspace lifecycle

The runner SHALL offer, under `/v1/workspaces`: create a workspace, read one workspace, list workspaces, run a command, read a file, write a file, copy a folder out as a tar archive, and destroy a workspace. Errors SHALL be RFC 7807 problem details of content type `application/problem+json` with the fields `type` (`https://ascend.ai/errors/` followed by the code with every `_` replaced by `-`), `title` (the HTTP reason phrase), `status`, `detail`, `instance` (the request path), a stable snake case `code` at the top level of the body and `traceId` (the trace id of the current trace), plus `errors` with the validation messages on a validation failure, the same fields and rules the agent uses. The body SHALL NOT carry a `timestamp` field. Create SHALL answer 201 with the workspace id, its state, its limits, its network mode and its expiry time. Destroy SHALL answer 204 when it removed the workspace and 404 when the workspace does not exist, is already destroyed or belongs to another tenant, so a client treats 404 on destroy as already done.

A command call SHALL take the command as one string run by the workspace's shell, an optional working folder inside `/workspace`, and an optional timeout in seconds no larger than the configured maximum. It SHALL answer with the exit code, standard output, standard error, whether each output was cut at the configured size limit, the duration, and whether the timeout ended the command. A command that runs past its timeout SHALL be killed together with every process it started, and its answer SHALL report `timedOut: true`. A workspace SHALL run one command or file operation at a time, and a call that arrives while another is running in the same workspace SHALL be answered 409 with code `workspace_busy`.

File paths SHALL be relative to `/workspace`. A path that is absolute, that contains a `..` segment after normalisation, or that contains a NUL character SHALL be answered 400 without touching the workspace. A file read SHALL refuse a file larger than the configured read limit with 413. A file write SHALL refuse a body larger than the configured write limit with 413. A folder copy SHALL stop at the configured archive limit and answer 413 when the folder is larger. Every file operation SHALL be carried out inside the workspace container, so a symbolic link inside the workspace can only ever point at files of that same workspace.

#### Scenario: Run a command

- **WHEN** a client runs `echo hello` in a ready workspace
- **THEN** the answer has exit code 0, standard output `hello` and `timedOut: false`

#### Scenario: Timeout kills the command and its children

- **WHEN** a client runs `sleep 600 & sleep 600` with a timeout of 2 seconds
- **THEN** the answer arrives within the timeout plus the configured margin and reports `timedOut: true`
- **AND** a following `ps` in the same workspace shows no `sleep` process

#### Scenario: One operation at a time

- **WHEN** a client runs a second command in a workspace while the first is still running
- **THEN** the second answer is 409 with code `workspace_busy`
- **AND** the first command is not affected

#### Scenario: Output is cut at the limit

- **WHEN** a command writes more than the configured output limit to standard output
- **THEN** the answer carries exactly the limit of bytes and `stdoutTruncated: true`

#### Scenario: Path traversal is refused

- **WHEN** a client reads the file `../../etc/passwd`
- **THEN** the answer is 400 with code `invalid_path`
- **AND** no command is run in the workspace

#### Scenario: A symbolic link stays inside the workspace

- **WHEN** a command creates `/workspace/link` pointing at `/etc/hostname` and a client reads `link`
- **THEN** the content returned is the workspace container's own `/etc/hostname`, never a file of the host or of the runner

#### Scenario: Write then read

- **WHEN** a client writes `out/result.txt` with the content `42` and then reads it
- **THEN** the read returns `42`

#### Scenario: Copy a folder out

- **WHEN** a client copies the folder `out` of a workspace that holds two files there
- **THEN** the answer is a tar archive holding both files with their relative paths

#### Scenario: Destroy twice

- **WHEN** a client destroys a workspace and then destroys it again
- **THEN** the first answer is 204 and the second is 404
- **AND** no container, network or proxy of that workspace exists afterwards

### Requirement: Workspaces are isolated from the host, the agent and each other

Each workspace SHALL be exactly one container used by exactly one workspace and destroyed with it. Under the `production` profile every workspace container SHALL run on the configured user space kernel runtime, and the runner SHALL refuse to start when that runtime is not registered in the container engine. Only workspace containers SHALL run on the user space kernel runtime: the runner SHALL set the engine's default runtime explicitly on every other container it creates, such as an egress proxy, and under the `production` profile it SHALL refuse to start when the engine's default runtime is the user space kernel runtime, so the runner and every other service of the platform keep the default runtime. Outside the `production` profile the runner MAY run workspaces on the engine's default runtime, and it SHALL then log a WARN line at startup that names the runtime and states that workspaces are not isolated at kernel level, and SHALL report the runtime in its readiness answer and as a metric tag.

Every workspace container SHALL: run as a non-root user, drop every Linux capability, set `no-new-privileges`, have a read-only root file system, have no host folder, socket or device mounted, publish no port, not be privileged, use only the engine's default system call filter or a stricter one, and carry no environment variable holding a secret of the platform. The one mount allowed is, for a profile marked `project-backed`, the one project folder of the coding project area described below. The only writable places SHALL be `/workspace` and `/tmp`, each limited in size. A request SHALL NOT be able to change any of these settings.

#### Scenario: No engine socket inside a workspace

- **WHEN** a command lists `/var/run/docker.sock` and `/run/docker.sock` in a workspace
- **THEN** neither exists

#### Scenario: No capabilities

- **WHEN** a command reads the effective capability set of its own process
- **THEN** the set is empty

#### Scenario: Privilege tricks fail

- **WHEN** a command tries `mount`, `unshare --user --map-root-user`, `nsenter`, `chroot` or a set-user-id binary
- **THEN** each attempt fails and the user stays the non-root workspace user

#### Scenario: Root file system is read-only

- **WHEN** a command writes a file under `/usr` or `/etc`
- **THEN** the write fails with a read-only file system error
- **AND** a write under `/workspace` succeeds

#### Scenario: No platform secret in the environment

- **WHEN** a command prints its whole environment
- **THEN** no variable of the agent's or the runner's configuration appears, including provider keys, database passwords, object store keys and the runner token

#### Scenario: Production refuses the shared-kernel runtime

- **WHEN** the runner starts with the `production` profile on an engine without the user space kernel runtime
- **THEN** startup fails with a message naming the missing runtime

#### Scenario: Platform services keep the default runtime

- **WHEN** a workspace with a network allow list is created under the `production` profile
- **THEN** the workspace container runs on the user space kernel runtime
- **AND** its egress proxy container and the runner container run on the engine's default runtime

#### Scenario: Production refuses a user space kernel default runtime

- **WHEN** the runner starts with the `production` profile on an engine whose default runtime is the user space kernel runtime
- **THEN** startup fails with a message that names the default runtime

#### Scenario: Production workspaces use the user space kernel

- **WHEN** a command in a workspace created under the `production` profile prints the kernel messages
- **THEN** the output identifies the user space kernel, not the host kernel

### Requirement: Resource and time limits come from configuration

The runner SHALL apply to every workspace a CPU limit, a memory limit, a process count limit, a size limit on `/workspace` and on `/tmp`, and a maximum lifetime, each read from configuration with a default. A create request MAY ask for a shorter lifetime. A create request MAY ask for lower limits and SHALL be answered 400 with code `limit_too_high` when it asks for a value above the configured maximum. The runner SHALL refuse to start when any limit is zero or negative. The runner SHALL also enforce a maximum number of workspaces per tenant and in total, and answer a create beyond either with 429 and code `too_many_workspaces`. Exhausting a limit inside a workspace SHALL affect only that workspace, and the runner and the other workspaces SHALL keep answering.

#### Scenario: Process bomb is contained

- **WHEN** a command starts processes in an endless loop
- **THEN** process creation fails once the process limit is reached
- **AND** the runner's health endpoint and a command in another workspace still answer in time

#### Scenario: Memory hog is contained

- **WHEN** a command allocates more memory than the workspace limit
- **THEN** the command is killed and its answer reports a non-zero exit code
- **AND** the workspace can still be destroyed

#### Scenario: Disk fill is contained

- **WHEN** a command writes more data under `/workspace` than its size limit
- **THEN** the write fails with no space left on the device

#### Scenario: Limit above the maximum

- **WHEN** a create request asks for more memory than the configured maximum
- **THEN** the answer is 400 with code `limit_too_high`

#### Scenario: Lifetime expires

- **WHEN** a workspace reaches its maximum lifetime
- **THEN** the runner destroys it
- **AND** a following call naming it answers 404

#### Scenario: Too many workspaces

- **WHEN** a tenant already has the configured maximum of workspaces and creates one more
- **THEN** the answer is 429 with code `too_many_workspaces`

### Requirement: Network access is off by default and follows an allow list when given

A workspace SHALL have no network at all unless its create request gives an allow list of host names. With no network, every connection attempt and every name lookup from inside the workspace SHALL fail. With an allow list, the workspace SHALL reach the outside only through a proxy that belongs to that workspace alone, and the proxy SHALL allow only connections to the listed host names, where an entry MAY start with `*.` to allow sub-domains. The proxy SHALL refuse every destination that resolves to a private, loopback, link-local, multicast or otherwise not publicly routable address, even when the host name is on the list. A direct connection from the workspace that does not use the proxy SHALL fail. Name lookups from inside the workspace SHALL fail, so names are resolved only by the proxy. The allow list SHALL be checked against the configured maximum length and a host name syntax, and SHALL never accept an IP address, a port range or a bare `*`.

#### Scenario: No network by default

- **WHEN** a command in a workspace created without an allow list connects to `https://example.com`
- **THEN** the connection fails
- **AND** a name lookup of `example.com` fails

#### Scenario: Allowed host works

- **WHEN** a workspace is created with the allow list `pypi.org,*.pythonhosted.org` and a command downloads a package index page from `https://pypi.org/simple/` through the proxy
- **THEN** the download succeeds

#### Scenario: Host not on the list

- **WHEN** a command in that workspace connects to `https://example.com` through the proxy
- **THEN** the proxy refuses the connection

#### Scenario: Internal services stay unreachable

- **WHEN** a command in any workspace tries to reach `ascend-agent`, `ascend-sandbox-runner`, `host.docker.internal`, the host's address on the default bridge network, `169.254.169.254` or the address of another workspace, directly or through the proxy
- **THEN** every attempt fails

#### Scenario: Allowed name that points inside

- **WHEN** an allowed host name resolves to a private address
- **THEN** the proxy refuses the connection

#### Scenario: Bypassing the proxy fails

- **WHEN** a command in a workspace with an allow list connects directly to a public address without the proxy
- **THEN** the connection fails

### Requirement: Workspaces start only from configured image profiles

A create request SHALL name an image profile, never an image reference. The runner SHALL know only the profiles in its configuration, each pinned to an image digest, and SHALL answer an unknown profile with 400 and code `unknown_profile`. The runner SHALL make sure every profile's image is present when it starts and SHALL NOT pull an image while a workspace is being created. A profile image that is missing at startup SHALL make the runner report not ready until it is present. The base profile image SHALL be built in this repository from a pinned base image, SHALL run as a non-root user, SHALL contain the shell and the tools the command, file and copy operations need, and SHALL be scanned for known vulnerabilities before it is used.

#### Scenario: Unknown profile

- **WHEN** a create request names a profile that is not configured
- **THEN** the answer is 400 with code `unknown_profile`

#### Scenario: Image name instead of a profile

- **WHEN** a create request carries a field naming an image such as `alpine:latest`
- **THEN** the answer is 400
- **AND** no image is pulled

#### Scenario: Create does not pull

- **WHEN** a workspace is created
- **THEN** no image pull is started by that request

### Requirement: Orphaned workspaces are removed after a crash

Every container, network and proxy that the runner creates SHALL carry labels naming the runner, the tenant, the workspace, the run or the conversation when one is given, and the expiry time. The runner SHALL keep no workspace record of its own, so the labels are the single record of what exists and a runner restart loses nothing. At startup and then on a configured interval, the runner SHALL remove every labelled container, proxy and network whose expiry time has passed, every proxy, credential gateway and network whose workspace container no longer exists, every area helper older than its timeout, and every labelled object whose labels cannot be read. An agent crash SHALL therefore leave workspaces only until their expiry plus one interval, and a runner crash SHALL leave nothing once the runner has started again and the expiry has passed. One runner SHALL run per container engine host and SHALL be shared by every agent copy on that host, and each runner SHALL list and remove only the objects of its own engine.

#### Scenario: Two agent copies share the runner of their host

- **WHEN** two agent copies on one container engine host each create a workspace
- **THEN** both workspaces are created by the one runner of that host and carry its labels
- **AND** its reaper removes both once their expiry has passed

#### Scenario: Agent crashes while a workspace is open

- **WHEN** the agent stops without destroying a workspace
- **THEN** the runner removes the workspace, its network and its proxy no later than one reaper interval after the workspace's expiry

#### Scenario: Runner restarts

- **WHEN** the runner is restarted while workspaces whose expiry has passed still exist
- **THEN** they are removed before the runner reports ready

#### Scenario: A half-created workspace is cleaned up

- **WHEN** the runner fails after creating a workspace's network and before starting its container
- **THEN** the next reaper pass removes that network

### Requirement: The runner reports logs, metrics and readiness

The runner SHALL expose a liveness endpoint, a readiness endpoint that is ready only when the container engine answers, the configured runtime is usable and every profile image is present, and a metrics endpoint on its private network. It SHALL count workspaces created, destroyed by reason, and active, commands by outcome, command duration, file operations by outcome, limit refusals by limit, reaper removals by kind, the seconds workspaces existed from creation to removal, credential gateways created and removed, area helper runs by operation and outcome, the free bytes of the coding project area, integration images built and refused, and integration services active, restarted, their seconds and their reserved memory, with the runtime or the area mode as a tag where it applies. No metric SHALL carry a tenant id, workspace id, run id or command text as a tag. Every log line written for a workspace SHALL carry the tenant id, the workspace id and the run id when known. Command text and file contents SHALL be logged only at DEBUG. One INFO line SHALL be written for every workspace created and destroyed and for every command finished, with its exit code, duration and output sizes.

#### Scenario: Sandbox time is counted

- **WHEN** a workspace that existed for 90 seconds is destroyed
- **THEN** the workspace seconds counter for its runtime grows by 90

#### Scenario: Readiness without the runtime

- **WHEN** the configured runtime is not registered in the engine and the profile is not `production`
- **THEN** readiness answers ready with the runtime reported as the engine's default
- **AND** the startup WARN line names it

#### Scenario: No command text at INFO

- **WHEN** a command containing the text `secret-marker-123` runs at log level INFO
- **THEN** no log line of the runner contains `secret-marker-123`

### Requirement: A project-backed workspace mounts exactly one project folder of the coding project area

The runner SHALL keep one coding project area, a named volume that in production is bound to a configured host folder, whenever a profile marked `project-backed` is configured, and SHALL need no area when none is. A create for a `project-backed` profile SHALL name one project, and the runner SHALL mount exactly that project's folder `tenants/<tenantId>/projects/<projectId>/` of the area at `/workspace`, as a subfolder mount of the area volume, in place of the size-limited `/workspace`. The runner SHALL build that path only from the tenant id of the request header and a validated project id, never from a free path, and SHALL build the mount so that no symbolic link inside the area can lead it out of that project folder. A create that names a project for a profile that is not `project-backed` SHALL be answered 400. A project folder that does not exist SHALL be answered 404 with code `project_not_found`. At most one workspace SHALL mount a project folder at a time, and a second create for the same project SHALL be answered 409 with code `project_busy`. Destroying the workspace SHALL keep the project folder. Every other isolation, limit, network and cleanup rule SHALL hold for a project-backed workspace as for any workspace. Under the `production` profile the runner SHALL refuse to start when the area is not bound to a configured host folder. Outside the `production` profile the area MAY be a plain named volume, and the runner SHALL then log one WARN line at startup and report the area mode in its readiness answer.

#### Scenario: Another project is not visible

- **WHEN** a command in the workspace of project `p1` searches every path it can reach for a file that only project `p2` holds
- **THEN** the file is not found

#### Scenario: A link does not escape

- **WHEN** a command in the workspace of project `p1` creates a symbolic link pointing at `../../p2` and at `/`, and reads through it
- **THEN** it reads only paths inside the workspace container's own view, never a file of `p2` or of the host

#### Scenario: Second workspace for the same project

- **WHEN** a workspace of project `p1` exists and a client creates another workspace for `p1`
- **THEN** the answer is 409 with code `project_busy`

#### Scenario: The folder outlives the workspace

- **WHEN** a workspace of project `p1` writes `repo/notes.md` and is destroyed, and a new workspace of `p1` is created
- **THEN** the new workspace finds `repo/notes.md`

#### Scenario: Production refuses the development area

- **WHEN** the runner starts under the `production` profile with a `project-backed` profile and the area in development mode
- **THEN** the runner does not start and its log names the setting

### Requirement: Coding project area operations run in helper containers

The runner SHALL offer, tenant scoped like every call, endpoints to create a project folder with its fixed subfolders, to read the size and free space of the area, to read the size of one project folder, to delete one project folder, and to stream one project folder as a gzip tar archive for export. Each operation SHALL run in a short-lived helper container that has no network and no capability, has a read-only root file system, mounts only the area, runs no project code, and is removed when the operation ends or its timeout passes. Delete and archive SHALL be answered 409 with code `project_busy` while a workspace mounts the project and SHALL never follow a symbolic link out of the folder, and delete SHALL check that the folder is gone. A project folder of another tenant SHALL be answered 404. The runner SHALL keep no record of projects of its own.

#### Scenario: Create a project folder

- **WHEN** a client creates the folder of a new project
- **THEN** the folder holds the subfolders `repo`, `home`, `tmp`, `out` and `run`, owned by the workspace user
- **AND** no helper container is left afterwards

#### Scenario: Delete keeps other projects

- **WHEN** a client deletes the folder of project `p1`, which holds a symbolic link to project `p2`
- **THEN** the folder of `p1` is gone and every file of `p2` still exists

#### Scenario: Archive of a project folder

- **WHEN** a client asks for the archive of project `p1`, which holds a file and a symbolic link to project `p2`
- **THEN** the answer is a gzip tar archive holding the file of `p1` and the link as a link
- **AND** no file of `p2` is in the archive and no helper container is left afterwards

### Requirement: A credential gateway holds the secrets of a workspace or a service

When a workspace or an integration service needs authenticated calls, the runner SHALL start one credential gateway container for it alone, next to its egress proxy, on the engine's default runtime. The gateway SHALL forward only the configured paths of each route to that route's fixed upstream, SHALL set only that route's header, SHALL refuse every other path with 403, and SHALL answer requests above a route's rate per minute with 429. An upstream SHALL never be a private address unless the runner's configuration lists it. Each secret SHALL be written by the runner into a memory-backed file inside the gateway that only the gateway process can read, through standard input, and SHALL never be put into an environment variable, a label, a command argument, a log line or an answer of the runner. The runner SHALL keep no copy of a secret it was sent. The workspace view SHALL name the routes only. The gateway SHALL log one line per request with the route, the method, the path without its query, the status, the duration and the bytes, and never a header, a query string or a body. A workspace SHALL reach its gateway by the fixed name `gateway`, without its egress proxy.

#### Scenario: The secret is not visible

- **WHEN** the container inspect output of a workspace and of its gateway is searched for a route's secret, and a command in the workspace tries to read the gateway's secret file
- **THEN** the secret is not found and the read fails

#### Scenario: Unlisted path

- **WHEN** a command in the workspace sends a request to a path of a route that the route does not list
- **THEN** the gateway answers 403 and nothing reaches the upstream

#### Scenario: Gateway log line

- **WHEN** a workspace sends one request through a route of its gateway
- **THEN** the gateway logs one line with the route, the method, the path and the status, and no header value

### Requirement: The egress proxy image has an open mode that the runner never uses

The egress proxy image SHALL accept an allow list of exactly `*`, which allows every public destination and SHALL still refuse every destination that resolves to a private, loopback, link-local, multicast or otherwise not publicly routable address. The runner SHALL never start a proxy in that mode, because its allow-list check refuses a bare `*`. When the allow list of a proxy changes, the runner SHALL replace the proxy container instead of reloading it.

#### Scenario: Open mode keeps the private address refusal

- **WHEN** a proxy started with the allow list `*` is asked for a public host and for a host that resolves to a private address
- **THEN** the public host is reached and the private address is refused

### Requirement: Integration images are assembled without running any code

The runner SHALL build an integration image only from a profile marked for images and two tar archives, the source and the dependencies. It SHALL check each archive before use and SHALL refuse with 400 and code `archive_refused` an archive that holds anything other than regular files and folders, a path that is absolute, holds `..` or a NUL character or is longer than 1024 bytes, a set-user-id or set-group-id bit, or more entries or bytes than its configured bounds. It SHALL create a container from the profile's pinned image with no network, SHALL never start it, SHALL copy the archives into it, SHALL commit it with a fixed user, command, environment and labels, SHALL remove the container, and SHALL answer with the image id and the SHA-256 of each archive. Images SHALL be tenant scoped and SHALL be deleted only after the tenant check.

#### Scenario: A refused archive

- **WHEN** a client sends a source archive that holds the path `../etc/passwd`
- **THEN** the answer is 400 with code `archive_refused` and no image is made

#### Scenario: Nothing runs during the build

- **WHEN** an image is built from two valid archives
- **THEN** the engine's events show that no container was started for it
- **AND** the image holds exactly the files of the two archives

### Requirement: Integration services are long-lived and kept equal to their requested state

The runner SHALL run an integration service as one container with its own internal network, its own egress proxy and its own credential gateway, created or replaced by one request that states the whole wanted state, and SHALL recreate only the parts whose requested state changed. A service container SHALL run under the same isolation rules as a workspace, SHALL have no expiry, SHALL never be removed by the reaper, SHALL not count against the maximum number of workspaces, and SHALL be adopted by its labels when the runner starts, without being restarted. A proxy, gateway or network whose service container no longer exists SHALL be removed. A service's gateway SHALL be the only member of the service network that also joins the ingress network the agent is on.

#### Scenario: Same request twice

- **WHEN** a client sends the same service request twice
- **THEN** the second request recreates no container

#### Scenario: Runner restart

- **WHEN** the runner restarts while an integration service runs
- **THEN** the service container keeps running and the runner reports it after startup

### Requirement: Integration secrets come only from the runner's own secrets file

The runner SHALL read integration secrets only from environment variables given to it by an optional secrets file of its own, never from the stack's main secrets file. The name of each variable SHALL be derived by the runner from the service's integration id and the credential name. A request SHALL never carry a secret value or a variable name, and the runner SHALL refuse a request that tries. The runner SHALL write a secret only into the service gateway's memory-backed file, and SHALL report per credential route only whether its value is present. A route whose variable is missing or empty SHALL not be created.

#### Scenario: Missing value

- **WHEN** a service names a credential whose variable is not set in the runner's environment
- **THEN** the service view reports `secretPresent: false` for that route and the gateway has no such route

#### Scenario: Value never leaves the runner

- **WHEN** a service with a present credential is created and its view, the inspect output of its containers and the runner's log are searched for the value
- **THEN** the value is not found
