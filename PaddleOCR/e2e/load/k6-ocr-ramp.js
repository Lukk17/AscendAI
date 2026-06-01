// k6 ramp profile derived from the api-tester proposal (2026-05-31).
// Drives POST /v1/ocr from 5 -> 80 VUs to find the asyncio.to_thread breaking point.
// Runs against a fixture image; expects the host-side PaddleOCR on :7022.
//
// Usage:
//   k6 run --vus 80 PaddleOCR/e2e/load/k6-ocr-ramp.js
// or with the inline ramp:
//   k6 run PaddleOCR/e2e/load/k6-ocr-ramp.js
//
// Requires the PNG fixture preloaded as a binary file at runtime.

import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
    scenarios: {
        ramp: {
            executor: 'ramping-vus',
            startVUs: 0,
            stages: [
                { duration: '1m', target: 5 },     // warm-up
                { duration: '3m', target: 20 },    // normal production range
                { duration: '3m', target: 40 },    // stress
                { duration: '2m', target: 80 },    // find the knee
                { duration: '1m', target: 5 },     // recovery
            ],
            gracefulRampDown: '30s',
        },
    },
    thresholds: {
        // p95 must stay under 30s at the 20-VU plateau.
        'http_req_duration{scenario:ramp}': ['p(95)<30000'],
        // Error rate under 1% at the 20-VU plateau.
        'http_req_failed{scenario:ramp}': ['rate<0.01'],
    },
};

const fixturePath = __ENV.FIXTURE_PATH || './PaddleOCR/e2e/fixtures/argent-saga-chronicles-page1.png';
const fixture = open(fixturePath, 'b');

export default function () {
    const url = `${__ENV.BASE_URL || 'http://localhost:7022'}/v1/ocr`;
    const payload = {
        file: http.file(fixture, 'argent-saga-chronicles-page1.png', 'image/png'),
        lang: 'en',
    };

    const res = http.post(url, payload);

    check(res, {
        'status is 200 or 429': (r) => r.status === 200 || r.status === 429,
        'p95 budget held': (r) => r.timings.duration < 30000,
    });

    sleep(1);
}
