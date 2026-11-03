# Actuator exposure: run tasks template

Spec: [../3-actuator-exposure-test.md](../3-actuator-exposure-test.md)

Copy this file to `../runs/<UTC-timestamp>_3-actuator-exposure-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] The agent shows a healthy state in `docker compose ps ascend-agent`

### Reset state

- [ ] None required

### Run

- [ ] `curl -s -o /dev/null -w "%{http_code}" http://localhost:9917/actuator/prometheus` prints `404`
- [ ] `curl -s http://localhost:9918/actuator/health` from the host fails to connect
- [ ] Metrics read from `http://ascend-agent:9918/actuator/prometheus` on the compose network
- [ ] Closed agent endpoints answer 404 from inside the network (`env`, `heapdump`, `threaddump`, `loggers`, `caches`)
- [ ] Closed endpoints answer 404 on `http://localhost:9998` from the host (`env`, `heapdump`, `threaddump`, `loggers`, `caches`)
- [ ] Weather metrics read from `http://localhost:9998/actuator/prometheus`

### Expected

- [ ] Every sample line of the agent metrics carries `service="ascend-agent"`
- [ ] Every sample line of the weather metrics carries `service="ascend-weather-mcp"`
- [ ] No assertion reads anything but status codes, connection results and metric lines

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary



Input tokens:

Output tokens:

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
