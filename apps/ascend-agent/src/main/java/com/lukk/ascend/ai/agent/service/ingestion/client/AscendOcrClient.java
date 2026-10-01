package com.lukk.ascend.ai.agent.service.ingestion.client;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.config.properties.AscendOcrProperties;
import com.lukk.ascend.ai.agent.exception.IngestionException;
import com.lukk.ascend.ai.agent.service.ingestion.IngestionMetadataKeys;
import com.lukk.ascend.ai.agent.util.NamedByteArrayResource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.document.Document;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;
import software.amazon.awssdk.core.exception.SdkException;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.ThreadLocalRandom;

@Slf4j
@Component
public class AscendOcrClient {

    private static final String TYPE_ASCEND_OCR = "ascendocr";
    private static final String PARAM_FILE = "file";
    private static final String PARAM_LANG = "lang";

    private static final String JSON_JOB_ID = "job_id";
    private static final String JSON_STATE = "state";
    private static final String JSON_POLL_AFTER_SECONDS = "poll_after_seconds";
    private static final String JSON_ERROR_CODE = "error_code";
    private static final String JSON_ERROR_REASON = "error_reason";
    private static final String JSON_RESULT = "result";
    private static final String JSON_BUCKET = "bucket";
    private static final String JSON_KEY = "key";
    private static final String JSON_CODE = "code";

    private static final String STATE_SUCCEEDED = "succeeded";
    private static final String STATE_FAILED = "failed";
    private static final String STATE_CANCELLED = "cancelled";

    private static final String CODE_QUEUE_FULL = "QUEUE_FULL";
    // ascend-ocr records these two when nothing was learned about the document itself,
    // unlike OCR_FAILED which says the same document will fail the same way again.
    private static final Set<String> RESUBMITTABLE_FAILURE_CODES =
            Set.of("SERVICE_RESTARTED", "RESULT_STORE_UNAVAILABLE");

    private static final int MAX_SUBMISSIONS_PER_DOCUMENT = 2;
    private static final int RETRY_JITTER_FRACTION = 4;
    private static final int MILLIS_PER_SECOND = 1000;
    private static final String JOB_ID_TEMPLATE = "/{jobId}";

    private final RestClient restClient;
    private final ObjectMapper objectMapper;
    private final S3Client s3Client;
    private final AscendOcrProperties properties;

    public AscendOcrClient(
            @Qualifier("ingestionRestClient") RestClient restClient,
            ObjectMapper objectMapper,
            S3Client s3Client,
            AscendOcrProperties properties) {
        this.restClient = restClient;
        this.objectMapper = objectMapper;
        this.s3Client = s3Client;
        this.properties = properties;
    }

    public List<Document> process(byte[] fileBytes, String filename, String lang) {
        log.info("[AscendOcrClient] Sending file to ascend-ocr: {}", filename);

        JobRecord succeeded = readDocument(fileBytes, filename, lang);
        String markdown = fetchResult(succeeded, filename);

        deleteJob(succeeded.jobId(), filename);

        return toDocuments(markdown, filename);
    }

    private JobRecord readDocument(byte[] fileBytes, String filename, String lang) {
        int submissions = 0;

        while (true) {
            submissions++;
            String jobId = submitJob(fileBytes, filename, lang);
            JobRecord record = awaitTerminalState(jobId, filename);

            if (record.isSucceeded()) {
                return record;
            }
            if (!record.isResubmittable() || submissions == MAX_SUBMISSIONS_PER_DOCUMENT) {
                throw jobFailed(record, filename);
            }

            log.warn("[AscendOcrClient] ascend-ocr job {} for {} failed with {}, resubmitting once",
                    jobId, filename, record.errorCode());
        }
    }

    private String submitJob(byte[] fileBytes, String filename, String lang) {
        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add(PARAM_FILE, new NamedByteArrayResource(fileBytes, filename));
        // ascend-ocr's documented contract declares `lang` as a multipart form field on
        // POST /v1/ocr/jobs, not a query parameter.
        if (StringUtils.hasText(lang)) {
            body.add(PARAM_LANG, lang);
        }

        int maxAttempts = Math.max(1, properties.getSubmitRetryAttempts() + 1);
        int attempt = 0;

        while (true) {
            attempt++;
            try {
                String jobId = readJobId(postSubmission(body), filename);
                log.info("[AscendOcrClient] ascend-ocr accepted {} as job {}", filename, jobId);

                return jobId;

            } catch (RestClientResponseException e) {
                if (!isQueueFull(e) || attempt == maxAttempts) {
                    throw submitRefused(filename, e);
                }

                log.warn("[AscendOcrClient] ascend-ocr refused {} with {}, retrying (attempt {}/{})",
                        filename, CODE_QUEUE_FULL, attempt, maxAttempts);
                sleep(submitRetryDelay(e));

            } catch (RestClientException e) {
                // A lost response may be hiding an accepted job, so a transport failure is never retried.
                throw new IngestionException("Failed to submit document to ascend-ocr: " + filename, e);
            }
        }
    }

    private ResponseEntity<String> postSubmission(MultiValueMap<String, Object> body) {
        return restClient.post()
                .uri(jobsUri())
                .contentType(MediaType.MULTIPART_FORM_DATA)
                .body(body)
                .retrieve()
                .toEntity(String.class);
    }

    private String readJobId(ResponseEntity<String> response, String filename) {
        if (!response.getStatusCode().isSameCodeAs(HttpStatus.ACCEPTED)) {
            throw new IngestionException("ascend-ocr answered " + response.getStatusCode().value()
                    + " instead of 202 when submitting " + filename);
        }

        String jobId = readTree(response.getBody()).path(JSON_JOB_ID).asText("");
        if (!StringUtils.hasText(jobId)) {
            throw new IngestionException("ascend-ocr accepted " + filename + " without a job identifier");
        }
        verifyLocation(response, jobId, filename);

        return jobId;
    }

    private void verifyLocation(ResponseEntity<String> response, String jobId, String filename) {
        String location = response.getHeaders().getFirst(HttpHeaders.LOCATION);
        if (location == null) {
            return;
        }

        String named = location.substring(location.lastIndexOf('/') + 1);
        if (!jobId.equals(named)) {
            throw new IngestionException("ascend-ocr accepted " + filename + " as job " + jobId
                    + " but pointed Location at " + location);
        }
    }

    private JobRecord awaitTerminalState(String jobId, String filename) {
        Instant deadline = Instant.now().plus(properties.getPollTimeout());

        while (true) {
            JobRecord record = readJob(jobId, filename);
            if (record.isTerminal()) {
                return record;
            }

            Duration remaining = Duration.between(Instant.now(), deadline);
            if (!remaining.isPositive()) {
                log.warn("[AscendOcrClient] Cancelling ascend-ocr job {} for {} after waiting {}",
                        jobId, filename, properties.getPollTimeout());
                deleteJob(jobId, filename);

                throw new IngestionException("ascend-ocr job " + jobId + " for " + filename
                        + " did not finish within " + properties.getPollTimeout());
            }

            sleep(shorterOf(record.pollDelay(), remaining));
        }
    }

    private JobRecord readJob(String jobId, String filename) {
        try {
            String body = restClient.get()
                    .uri(jobUriTemplate(), jobId)
                    .retrieve()
                    .body(String.class);

            return parseRecord(body, jobId);

        } catch (RestClientException e) {
            throw new IngestionException("Failed to read ascend-ocr job " + jobId + " for " + filename, e);
        }
    }

    private JobRecord parseRecord(String body, String jobId) {
        JsonNode root = readTree(body);

        String state = root.path(JSON_STATE).asText("");
        if (!StringUtils.hasText(state)) {
            throw new IngestionException("ascend-ocr job " + jobId + " reported no state");
        }

        JsonNode result = root.path(JSON_RESULT);
        JobRecord record = new JobRecord(
                jobId,
                state,
                clampPollDelay(root.path(JSON_POLL_AFTER_SECONDS).asDouble(0)),
                root.path(JSON_ERROR_CODE).asText(""),
                root.path(JSON_ERROR_REASON).asText(""),
                new ResultReference(result.path(JSON_BUCKET).asText(""), result.path(JSON_KEY).asText("")));

        if (record.isSucceeded() && !record.result().isAddressable()) {
            throw new IngestionException("ascend-ocr job " + jobId + " succeeded without a result address");
        }

        return record;
    }

    private Duration clampPollDelay(double hintSeconds) {
        long hintMillis = Math.round(hintSeconds * MILLIS_PER_SECOND);

        return Duration.ofMillis(Math.clamp(hintMillis,
                properties.getPollMinInterval().toMillis(),
                properties.getPollMaxInterval().toMillis()));
    }

    private String fetchResult(JobRecord record, String filename) {
        ResultReference result = record.result();
        log.info("[AscendOcrClient] Fetching ascend-ocr result {}/{} for {}",
                result.bucket(), result.key(), filename);

        try {
            return s3Client.getObjectAsBytes(GetObjectRequest.builder()
                            .bucket(result.bucket())
                            .key(result.key())
                            .build())
                    .asUtf8String();

        } catch (SdkException e) {
            throw new IngestionException("Failed to fetch ascend-ocr result " + result.bucket() + "/"
                    + result.key() + " for " + filename, e);
        }
    }

    private void deleteJob(String jobId, String filename) {
        try {
            restClient.delete()
                    .uri(jobUriTemplate(), jobId)
                    .retrieve()
                    .toBodilessEntity();

        } catch (RestClientException e) {
            log.warn("[AscendOcrClient] Failed to delete ascend-ocr job {} for {}", jobId, filename, e);
        }
    }

    private List<Document> toDocuments(String markdown, String filename) {
        if (!StringUtils.hasText(markdown)) {
            log.warn("[AscendOcrClient] ascend-ocr produced an empty result for {}", filename);

            return List.of();
        }

        log.info("[AscendOcrClient] Extracted {} characters from {}", markdown.length(), filename);

        return List.of(new Document(markdown, Map.of(
                IngestionMetadataKeys.SOURCE, filename,
                IngestionMetadataKeys.TYPE, TYPE_ASCEND_OCR)));
    }

    private IngestionException jobFailed(JobRecord record, String filename) {
        StringBuilder message = new StringBuilder("ascend-ocr job ")
                .append(record.jobId())
                .append(" for ")
                .append(filename)
                .append(" finished as ")
                .append(record.state());

        if (StringUtils.hasText(record.errorCode())) {
            message.append(" [")
                    .append(record.errorCode())
                    .append("] ")
                    .append(record.errorReason());
        }

        return new IngestionException(message.toString());
    }

    private IngestionException submitRefused(String filename, RestClientResponseException failure) {
        String code = errorCode(failure).map(named -> " " + named).orElse("");

        return new IngestionException("ascend-ocr refused " + filename + " with status "
                + failure.getStatusCode().value() + code, failure);
    }

    private boolean isQueueFull(RestClientResponseException failure) {
        return failure.getStatusCode().isSameCodeAs(HttpStatus.SERVICE_UNAVAILABLE)
                && CODE_QUEUE_FULL.equals(errorCode(failure).orElse(""));
    }

    private Optional<String> errorCode(RestClientResponseException failure) {
        try {
            String code = objectMapper.readTree(failure.getResponseBodyAsString()).path(JSON_CODE).asText("");

            return StringUtils.hasText(code) ? Optional.of(code) : Optional.empty();

        } catch (JsonProcessingException e) {
            log.debug("[AscendOcrClient] ascend-ocr refusal carried no JSON body", e);

            return Optional.empty();
        }
    }

    private Duration submitRetryDelay(RestClientResponseException failure) {
        Duration base = shorterOf(
                retryAfter(failure).orElse(properties.getSubmitRetryMaxDelay()),
                properties.getSubmitRetryMaxDelay());
        long jitterMillis = ThreadLocalRandom.current().nextLong(1 + base.toMillis() / RETRY_JITTER_FRACTION);

        return base.plusMillis(jitterMillis);
    }

    private Optional<Duration> retryAfter(RestClientResponseException failure) {
        HttpHeaders headers = failure.getResponseHeaders();
        if (headers == null) {
            return Optional.empty();
        }

        String value = headers.getFirst(HttpHeaders.RETRY_AFTER);
        if (!StringUtils.hasText(value)) {
            return Optional.empty();
        }

        try {
            return Optional.of(Duration.ofSeconds(Math.max(0, Long.parseLong(value.trim()))));

        } catch (NumberFormatException e) {
            log.debug("[AscendOcrClient] ascend-ocr sent a Retry-After this client cannot read: {}", value);

            return Optional.empty();
        }
    }

    private JsonNode readTree(String body) {
        String payload = body == null ? "" : body;

        try {
            return objectMapper.readTree(payload);

        } catch (JsonProcessingException e) {
            throw new IngestionException("Failed to parse ascend-ocr JSON response", e);
        }
    }

    private void sleep(Duration duration) {
        try {
            Thread.sleep(duration);

        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();

            throw new IngestionException("Interrupted while waiting for ascend-ocr", e);
        }
    }

    private Duration shorterOf(Duration first, Duration second) {
        return first.compareTo(second) <= 0 ? first : second;
    }

    private String jobsUri() {
        return properties.getBaseUrl() + properties.getApiPath();
    }

    private String jobUriTemplate() {
        return jobsUri() + JOB_ID_TEMPLATE;
    }

    private record ResultReference(String bucket, String key) {

        private boolean isAddressable() {
            return StringUtils.hasText(bucket) && StringUtils.hasText(key);
        }
    }

    private record JobRecord(String jobId, String state, Duration pollDelay, String errorCode, String errorReason,
                             ResultReference result) {

        private boolean isSucceeded() {
            return STATE_SUCCEEDED.equals(state);
        }

        private boolean isTerminal() {
            return isSucceeded() || STATE_FAILED.equals(state) || STATE_CANCELLED.equals(state);
        }

        private boolean isResubmittable() {
            return STATE_FAILED.equals(state) && RESUBMITTABLE_FAILURE_CODES.contains(errorCode);
        }
    }
}
