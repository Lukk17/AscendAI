# Manual Interactive Tests

This collection contains tests that require human intervention and cannot pass unattended. These requests must be run deliberately, not as part of an automated test suite.

## What's in This Collection

Requests here interact with services or websites that present CAPTCHAs or other challenges that require a person to solve them in real time. Examples include:

- Websites protected by Cloudflare that demand CAPTCHA solutions
- Scenarios that require browser automation with human verification steps
- Tests that intentionally probe for human-in-the-loop behavior

## Why Separate

The main AscendAI collection runs as an automated suite via Bruno's batch runner. If these requests were included, they would stall indefinitely waiting for CAPTCHA input that never comes. Isolating them into their own collection lets you run them on purpose without breaking the automated flow.

## Related Automated Tests

The e2e test suite at `apps/ascend-web-hunter/e2e/testing/7-authenticated-realworld-scraping-test.md` exercises the same scenarios (authenticated reads, Cloudflare bypass) as part of the formal capability verification. That test is automated and does pass unattended. Use this manual collection when you want to poke at the behavior yourself with a browser open.

## How to Run a Request

Point your Bruno client at this collection and select an individual request to execute:

```bash
cd docs/api/request/manual-interactive-tests
```

Open the collection in Bruno and run a single request (never the whole collection via batch runner).

If the request returns a URL with a remote browser endpoint (such as a NoVNC tunnel), you can open that URL in your local browser and solve the CAPTCHA. The request will complete once the challenge is satisfied.

## Requests

### read-captcha

Tests the ascend-web-hunter web_read tool against https://nowsecure.nl, a site that always presents a Cloudflare challenge. The service responds with a remote browser URL if human intervention is needed.

Expected behavior: Status 200 with a response payload containing one of:
- status: "success" (cached response or served without challenge)
- status: "human_intervention_required" (browser URL provided for you to solve the CAPTCHA)
- status: "novnc_busy" (human intervention pending)

Never expect status: "error".
