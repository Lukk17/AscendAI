package com.lukk.ascend.ai.agent.service.ingestion.client;

import com.lukk.ascend.ai.agent.config.properties.AscendOcrProperties;
import lombok.AccessLevel;
import lombok.NoArgsConstructor;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import software.amazon.awssdk.core.ResponseBytes;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;
import software.amazon.awssdk.services.s3.model.GetObjectResponse;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Set;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withNoContent;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

@NoArgsConstructor(access = AccessLevel.PRIVATE)
final class AscendOcrJobFixtures {

    static final String BASE_URL = "http://localhost:7022";
    static final String JOBS_PATH = "/v1/ocr/jobs";
    static final String JOBS_URL = BASE_URL + JOBS_PATH;
    static final String JOB_ID = "tQ3v9ZkLx2Wm8aPbR5cN0g";
    static final String JOB_PATH = JOBS_PATH + "/" + JOB_ID;
    static final String JOB_URL = BASE_URL + JOB_PATH;
    static final String BUCKET = "ocr-results";
    static final String KEY = JOB_ID + ".md";
    static final String FILENAME = "invoice.png";
    static final byte[] FILE_BYTES = "image_data".getBytes(StandardCharsets.UTF_8);
    static final String MARKDOWN = "## Page 1\n\nTotal: $100\nTax: $5\n";
    private static final double SUBMITTED_AT = 1_700_000_000.0;
    private static final double STARTED_AT = 1_700_000_001.0;
    private static final double FINISHED_AT = 1_700_000_005.1;
    private static final Set<String> RETRYABLE_FAILURE_CODES = Set.of("SERVICE_RESTARTED", "RESULT_STORE_UNAVAILABLE");

    static AscendOcrProperties properties() {
        AscendOcrProperties properties = new AscendOcrProperties();
        properties.setBaseUrl(BASE_URL);
        properties.setApiPath(JOBS_PATH);
        properties.setPollMinInterval(Duration.ofMillis(1));
        properties.setPollMaxInterval(Duration.ofMillis(20));
        properties.setPollTimeout(Duration.ofSeconds(10));
        properties.setSubmitRetryAttempts(2);
        properties.setSubmitRetryMaxDelay(Duration.ofMillis(20));

        return properties;
    }

    static String acceptedBody() {
        return """
                {
                  "job_id": "%s",
                  "state": "waiting",
                  "page_count": 1,
                  "queue_position": 0,
                  "pages_ahead": 0,
                  "status_url": "%s",
                  "poll_after_seconds": 0.001
                }
                """.formatted(JOB_ID, JOB_PATH);
    }

    static String runningBody(double pollAfterSeconds) {
        return """
                {
                  "job_id": "%s",
                  "state": "running",
                  "page_count": 1,
                  "pages_done": 0,
                  "submitted_at": %s,
                  "started_at": %s,
                  "finished_at": null,
                  "queue_position": null,
                  "pages_ahead": null,
                  "poll_after_seconds": %s,
                  "error_code": null,
                  "error_reason": null,
                  "retryable": false,
                  "result": null
                }
                """.formatted(JOB_ID, SUBMITTED_AT, STARTED_AT, pollAfterSeconds);
    }

    static String succeededBody() {
        return succeededBody("");
    }

    static String succeededBodyWithNullPollHint() {
        return succeededBody("\"poll_after_seconds\": null,");
    }

    private static String succeededBody(String extraField) {
        return """
                {
                  "job_id": "%s",
                  "state": "succeeded",
                  %s
                  "page_count": 1,
                  "pages_done": 1,
                  "submitted_at": %s,
                  "started_at": %s,
                  "finished_at": %s,
                  "queue_position": null,
                  "pages_ahead": null,
                  "error_code": null,
                  "error_reason": null,
                  "retryable": false,
                  "result": {
                    "bucket": "%s",
                    "key": "%s",
                    "url": "http://localhost:9070/%s/%s?X-Amz-Signature=stub",
                    "schema_version": "1",
                    "filename": "%s",
                    "language": "en",
                    "quality": "high",
                    "straighten": false,
                    "page_count": 1,
                    "processing_time_seconds": 4.1
                  }
                }
                """.formatted(JOB_ID, extraField, SUBMITTED_AT, STARTED_AT, FINISHED_AT, BUCKET, KEY, BUCKET, KEY,
                FILENAME);
    }

    static String failedBody(String errorCode, String errorReason) {
        return """
                {
                  "job_id": "%s",
                  "state": "failed",
                  "page_count": 1,
                  "pages_done": 0,
                  "submitted_at": %s,
                  "started_at": %s,
                  "finished_at": %s,
                  "queue_position": null,
                  "pages_ahead": null,
                  "error_code": "%s",
                  "error_reason": "%s",
                  "retryable": %s,
                  "result": null
                }
                """.formatted(JOB_ID, SUBMITTED_AT, STARTED_AT, FINISHED_AT, errorCode, errorReason,
                RETRYABLE_FAILURE_CODES.contains(errorCode));
    }

    static String cancelledBody() {
        return """
                {
                  "job_id": "%s",
                  "state": "cancelled",
                  "page_count": 1,
                  "pages_done": 0,
                  "submitted_at": %s,
                  "started_at": %s,
                  "finished_at": %s,
                  "queue_position": null,
                  "pages_ahead": null,
                  "error_code": null,
                  "error_reason": null,
                  "retryable": false,
                  "result": null
                }
                """.formatted(JOB_ID, SUBMITTED_AT, STARTED_AT, FINISHED_AT);
    }

    static String queueFullBody() {
        return """
                {"code": "QUEUE_FULL", "detail": "Queue is full, retry later"}
                """;
    }

    static void expectSubmit(MockRestServiceServer server) {
        server.expect(requestTo(JOBS_URL))
                .andExpect(method(HttpMethod.POST))
                .andRespond(withStatus(HttpStatus.ACCEPTED)
                        .contentType(MediaType.APPLICATION_JSON)
                        .header(HttpHeaders.LOCATION, JOB_PATH)
                        .body(acceptedBody()));
    }

    static void expectStatus(MockRestServiceServer server, String body) {
        server.expect(requestTo(JOB_URL))
                .andExpect(method(HttpMethod.GET))
                .andRespond(withSuccess(body, MediaType.APPLICATION_JSON));
    }

    static void expectDelete(MockRestServiceServer server) {
        server.expect(requestTo(JOB_URL))
                .andExpect(method(HttpMethod.DELETE))
                .andRespond(withNoContent());
    }

    static void stubStoredResult(S3Client s3Client, String markdown) {
        when(s3Client.getObjectAsBytes(any(GetObjectRequest.class)))
                .thenReturn(ResponseBytes.fromByteArray(GetObjectResponse.builder().build(),
                        markdown.getBytes(StandardCharsets.UTF_8)));
    }
}
