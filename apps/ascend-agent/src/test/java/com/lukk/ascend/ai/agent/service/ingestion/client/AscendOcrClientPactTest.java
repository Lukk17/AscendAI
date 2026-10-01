package com.lukk.ascend.ai.agent.service.ingestion.client;

import au.com.dius.pact.consumer.MockServer;
import au.com.dius.pact.consumer.dsl.PactDslJsonBody;
import au.com.dius.pact.consumer.dsl.PactDslResponse;
import au.com.dius.pact.consumer.dsl.PactDslWithProvider;
import au.com.dius.pact.consumer.dsl.PactDslWithState;
import au.com.dius.pact.consumer.junit5.PactConsumerTestExt;
import au.com.dius.pact.consumer.junit5.PactTestFor;
import au.com.dius.pact.core.model.PactSpecVersion;
import au.com.dius.pact.core.model.V4Pact;
import au.com.dius.pact.core.model.annotations.Pact;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.config.properties.AscendOcrProperties;
import com.lukk.ascend.ai.agent.exception.IngestionException;
import org.apache.hc.client5.http.entity.mime.ByteArrayBody;
import org.apache.hc.client5.http.entity.mime.FormBodyPart;
import org.apache.hc.client5.http.entity.mime.FormBodyPartBuilder;
import org.apache.hc.client5.http.entity.mime.MultipartEntityBuilder;
import org.apache.hc.client5.http.entity.mime.StringBody;
import org.apache.hc.core5.http.ContentType;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.springframework.ai.document.Document;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.awt.image.DataBufferByte;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.BUCKET;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.FILENAME;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.JOBS_PATH;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.JOB_ID;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.JOB_PATH;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.KEY;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.MARKDOWN;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.properties;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.stubStoredResult;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

@ExtendWith(PactConsumerTestExt.class)
@PactTestFor(providerName = AscendOcrClientPactTest.PROVIDER, pactVersion = PactSpecVersion.V4)
class AscendOcrClientPactTest {

    static final String CONSUMER = "ascend-agent";
    static final String PROVIDER = "ascend-ocr";

    private static final String QUEUE_HAS_ROOM = "the queue has room";
    private static final String QUEUE_IS_FULL = "the queue is full";
    private static final String JOB_IS_WAITING = "job {jobId} is waiting";
    private static final String JOB_IS_RUNNING = "job {jobId} is running";
    private static final String JOB_HAS_SUCCEEDED = "job {jobId} has succeeded";
    private static final String JOB_HAS_FAILED = "job {jobId} has failed";
    private static final String JOB_WAS_CANCELLED = "job {jobId} was cancelled";
    private static final String NO_JOB_EXISTS = "no job {jobId} exists";

    private static final String PARAM_JOB_ID = "jobId";
    private static final String PARAM_ERROR_CODE = "errorCode";

    private static final String CODE_OCR_FAILED = "OCR_FAILED";
    private static final String CODE_SERVICE_RESTARTED = "SERVICE_RESTARTED";
    private static final String CODE_RESULT_STORE_UNAVAILABLE = "RESULT_STORE_UNAVAILABLE";

    private static final String JOB_ID_PATTERN = "[A-Za-z0-9_-]{22}";
    private static final String LOCATION_PATTERN = "^/v1/ocr/jobs/[A-Za-z0-9_-]{22}$";
    private static final String RETRY_AFTER_PATTERN = "^\\d+$";
    private static final String NON_EMPTY_PATTERN = ".+";

    private static final String LANG_ENGLISH = "en";
    private static final String LANG_UNSUPPORTED = "xx";
    private static final String TEXT_FILENAME = "notes.txt";
    private static final byte[] TEXT_BYTES = "plain text, not an image".getBytes(StandardCharsets.UTF_8);
    private static final int PNG_SIDE_PIXELS = 10;
    private static final byte WHITE = (byte) 0xFF;
    private static final byte[] PNG_BYTES = whitePng();

    private static final String MULTIPART_BOUNDARY = "ascend-agent-pact-boundary";
    private static final String CONTENT_DISPOSITION = "Content-Disposition";
    private static final String CONTENT_TYPE = "Content-Type";
    private static final String MEDIA_PNG = "image/png";
    private static final String MEDIA_TEXT = "text/plain";
    private static final String MEDIA_TEXT_UTF8 = "text/plain;charset=UTF-8";
    private static final String PART_FILE = "file";
    private static final String PART_LANG = "lang";

    private final List<HttpMethod> sentMethods = new ArrayList<>();
    private final S3Client s3Client = mock(S3Client.class);

    @Pact(consumer = CONSUMER, provider = PROVIDER)
    public V4Pact succeededWithLanguage(PactDslWithProvider builder) {
        PactDslResponse submitted = submitPngInEnglish(builder.given(QUEUE_HAS_ROOM));
        PactDslResponse read = readSucceededJob(submitted.given(JOB_HAS_SUCCEEDED, jobState()));

        return deleteSucceededJob(read.given(JOB_HAS_SUCCEEDED, jobState())).toPact(V4Pact.class);
    }

    @Pact(consumer = CONSUMER, provider = PROVIDER)
    public V4Pact succeededWithoutLanguage(PactDslWithProvider builder) {
        PactDslResponse submitted = submitPngWithoutLanguage(builder.given(QUEUE_HAS_ROOM));
        PactDslResponse read = readSucceededJob(submitted.given(JOB_HAS_SUCCEEDED, jobState()));

        return deleteSucceededJob(read.given(JOB_HAS_SUCCEEDED, jobState())).toPact(V4Pact.class);
    }

    @Pact(consumer = CONSUMER, provider = PROVIDER)
    public V4Pact queueIsFull(PactDslWithProvider builder) {
        return builder.given(QUEUE_IS_FULL)
                .uponReceiving("a submission of a PNG while the queue is full")
                .path(JOBS_PATH)
                .method(HttpMethod.POST.name())
                .body(pngUpload(null))
                .willRespondWith()
                .status(503)
                .matchHeader(HttpHeaders.RETRY_AFTER, RETRY_AFTER_PATTERN, "1")
                .body(new PactDslJsonBody()
                        .stringValue("code", "QUEUE_FULL")
                        .stringType("detail", "Queue is full, retry later"))
                .toPact(V4Pact.class);
    }

    @Pact(consumer = CONSUMER, provider = PROVIDER)
    public V4Pact unsupportedFileType(PactDslWithProvider builder) {
        return builder.uponReceiving("a submission of a text file")
                .path(JOBS_PATH)
                .method(HttpMethod.POST.name())
                .body(textUpload())
                .willRespondWith()
                .status(400)
                .body(new PactDslJsonBody().stringValue("code", "UNSUPPORTED_FILE_TYPE"))
                .toPact(V4Pact.class);
    }

    @Pact(consumer = CONSUMER, provider = PROVIDER)
    public V4Pact unsupportedLanguage(PactDslWithProvider builder) {
        return builder.given(QUEUE_HAS_ROOM)
                .uponReceiving("a submission of a PNG in the unsupported language xx")
                .path(JOBS_PATH)
                .method(HttpMethod.POST.name())
                .body(pngUpload(LANG_UNSUPPORTED))
                .willRespondWith()
                .status(400)
                .body(new PactDslJsonBody().stringValue("code", "UNSUPPORTED_LANGUAGE"))
                .toPact(V4Pact.class);
    }

    @Pact(consumer = CONSUMER, provider = PROVIDER)
    public V4Pact waitingUntilPollTimeout(PactDslWithProvider builder) {
        PactDslResponse submitted = submitPngWithoutLanguage(builder.given(QUEUE_HAS_ROOM));
        PactDslResponse read = submitted.given(JOB_IS_WAITING, jobState())
                .uponReceiving("a status read of a waiting job")
                .path(JOB_PATH)
                .method(HttpMethod.GET.name())
                .willRespondWith()
                .status(200)
                .body(new PactDslJsonBody()
                        .stringMatcher("job_id", JOB_ID_PATTERN, JOB_ID)
                        .stringValue("state", "waiting")
                        .numberType("poll_after_seconds", 1));

        return deleteWaitingJob(read.given(JOB_IS_WAITING, jobState())).toPact(V4Pact.class);
    }

    @Pact(consumer = CONSUMER, provider = PROVIDER)
    public V4Pact runningUntilPollTimeout(PactDslWithProvider builder) {
        PactDslResponse submitted = submitPngWithoutLanguage(builder.given(QUEUE_HAS_ROOM));
        PactDslResponse read = submitted.given(JOB_IS_RUNNING, jobState())
                .uponReceiving("a status read of a running job")
                .path(JOB_PATH)
                .method(HttpMethod.GET.name())
                .willRespondWith()
                .status(200)
                .body(new PactDslJsonBody()
                        .stringValue("state", "running")
                        .numberType("poll_after_seconds", 1));

        return deleteRunningJob(read.given(JOB_IS_RUNNING, jobState())).toPact(V4Pact.class);
    }

    @Pact(consumer = CONSUMER, provider = PROVIDER)
    public V4Pact failedWithOcrFailed(PactDslWithProvider builder) {
        PactDslResponse submitted = submitPngWithoutLanguage(builder.given(QUEUE_HAS_ROOM));

        return readFailedJob(submitted, CODE_OCR_FAILED).toPact(V4Pact.class);
    }

    @Pact(consumer = CONSUMER, provider = PROVIDER)
    public V4Pact failedWithServiceRestarted(PactDslWithProvider builder) {
        PactDslResponse submitted = submitPngWithoutLanguage(builder.given(QUEUE_HAS_ROOM));

        return readFailedJob(submitted, CODE_SERVICE_RESTARTED).toPact(V4Pact.class);
    }

    @Pact(consumer = CONSUMER, provider = PROVIDER)
    public V4Pact failedWithResultStoreUnavailable(PactDslWithProvider builder) {
        PactDslResponse submitted = submitPngWithoutLanguage(builder.given(QUEUE_HAS_ROOM));

        return readFailedJob(submitted, CODE_RESULT_STORE_UNAVAILABLE).toPact(V4Pact.class);
    }

    @Pact(consumer = CONSUMER, provider = PROVIDER)
    public V4Pact cancelled(PactDslWithProvider builder) {
        PactDslResponse submitted = submitPngWithoutLanguage(builder.given(QUEUE_HAS_ROOM));

        return submitted.given(JOB_WAS_CANCELLED, jobState())
                .uponReceiving("a status read of a cancelled job")
                .path(JOB_PATH)
                .method(HttpMethod.GET.name())
                .willRespondWith()
                .status(200)
                .body(new PactDslJsonBody().stringValue("state", "cancelled"))
                .toPact(V4Pact.class);
    }

    @Pact(consumer = CONSUMER, provider = PROVIDER)
    public V4Pact unknownJobOnRead(PactDslWithProvider builder) {
        PactDslResponse submitted = submitPngWithoutLanguage(builder.given(QUEUE_HAS_ROOM));

        return submitted.given(NO_JOB_EXISTS, jobState())
                .uponReceiving("a status read of a job that does not exist")
                .path(JOB_PATH)
                .method(HttpMethod.GET.name())
                .willRespondWith()
                .status(404)
                .body(new PactDslJsonBody().stringValue("code", "JOB_NOT_FOUND"))
                .toPact(V4Pact.class);
    }

    @Pact(consumer = CONSUMER, provider = PROVIDER)
    public V4Pact failedDeleteAfterSuccess(PactDslWithProvider builder) {
        PactDslResponse submitted = submitPngWithoutLanguage(builder.given(QUEUE_HAS_ROOM));
        PactDslResponse read = readSucceededJob(submitted.given(JOB_HAS_SUCCEEDED, jobState()));

        return read.given(NO_JOB_EXISTS, jobState())
                .uponReceiving("a delete of a job that does not exist")
                .path(JOB_PATH)
                .method(HttpMethod.DELETE.name())
                .willRespondWith()
                .status(404)
                .toPact(V4Pact.class);
    }

    @Test
    @PactTestFor(pactMethod = "succeededWithLanguage")
    @DisplayName("process submits the file and its language, reads the stored result and deletes the job")
    void process_WhenJobSucceedsWithALanguage_ThenReturnsTheStoredResult(MockServer mockServer) {
        // given
        AscendOcrClient client = clientFor(mockServer, properties());
        stubStoredResult(s3Client, MARKDOWN);

        // when
        List<Document> documents = client.process(PNG_BYTES, FILENAME, LANG_ENGLISH);

        // then
        assertThat(documents).hasSize(1);
        assertThat(documents.getFirst().getText()).isEqualTo(MARKDOWN);
        assertFetchedResultFromTheRecordedAddress();
        assertThat(sentMethods).containsExactly(HttpMethod.POST, HttpMethod.GET, HttpMethod.DELETE);
    }

    @Test
    @PactTestFor(pactMethod = "succeededWithoutLanguage")
    @DisplayName("process submits the file alone when no language is given and returns the stored result")
    void process_WhenJobSucceedsWithoutALanguage_ThenReturnsTheStoredResult(MockServer mockServer) {
        // given
        AscendOcrClient client = clientFor(mockServer, properties());
        stubStoredResult(s3Client, MARKDOWN);

        // when
        List<Document> documents = client.process(PNG_BYTES, FILENAME, null);

        // then
        assertThat(documents).hasSize(1);
        assertThat(documents.getFirst().getText()).isEqualTo(MARKDOWN);
        assertFetchedResultFromTheRecordedAddress();
        assertThat(sentMethods).containsExactly(HttpMethod.POST, HttpMethod.GET, HttpMethod.DELETE);
    }

    @Test
    @PactTestFor(pactMethod = "queueIsFull")
    @DisplayName("process retries a queue-full refusal up to the configured attempts and then throws naming QUEUE_FULL")
    void process_WhenQueueStaysFull_ThenRetriesAndThrowsNamingTheCode(MockServer mockServer) {
        // given
        AscendOcrProperties properties = properties();
        AscendOcrClient client = clientFor(mockServer, properties);

        // then
        assertThatThrownBy(() -> client.process(PNG_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("503")
                .hasMessageContaining("QUEUE_FULL");
        assertThat(sentMethods)
                .hasSize(properties.getSubmitRetryAttempts() + 1)
                .containsOnly(HttpMethod.POST);
    }

    @Test
    @PactTestFor(pactMethod = "unsupportedFileType")
    @DisplayName("process throws naming UNSUPPORTED_FILE_TYPE when the service refuses a text file")
    void process_WhenFileTypeIsUnsupported_ThenThrowsNamingTheCode(MockServer mockServer) {
        // given
        AscendOcrClient client = clientFor(mockServer, properties());

        // then
        assertThatThrownBy(() -> client.process(TEXT_BYTES, TEXT_FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("with status 400 UNSUPPORTED_FILE_TYPE");
        assertThat(sentMethods).containsExactly(HttpMethod.POST);
    }

    @Test
    @PactTestFor(pactMethod = "unsupportedLanguage")
    @DisplayName("process throws naming UNSUPPORTED_LANGUAGE when the service refuses the language")
    void process_WhenLanguageIsUnsupported_ThenThrowsNamingTheCode(MockServer mockServer) {
        // given
        AscendOcrClient client = clientFor(mockServer, properties());

        // then
        assertThatThrownBy(() -> client.process(PNG_BYTES, FILENAME, LANG_UNSUPPORTED))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("with status 400 UNSUPPORTED_LANGUAGE");
        assertThat(sentMethods).containsExactly(HttpMethod.POST);
    }

    @Test
    @PactTestFor(pactMethod = "waitingUntilPollTimeout")
    @DisplayName("process deletes a job still waiting when its poll timeout expires and then throws")
    void process_WhenJobIsStillWaitingAtThePollTimeout_ThenDeletesTheJobAndThrows(MockServer mockServer) {
        // given
        AscendOcrClient client = clientFor(mockServer, expiredPollTimeout());

        // then
        assertThatThrownBy(() -> client.process(PNG_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("did not finish within");
        assertThat(sentMethods).containsExactly(HttpMethod.POST, HttpMethod.GET, HttpMethod.DELETE);
    }

    @Test
    @PactTestFor(pactMethod = "runningUntilPollTimeout")
    @DisplayName("process deletes a job still running when its poll timeout expires and then throws")
    void process_WhenJobIsStillRunningAtThePollTimeout_ThenDeletesTheJobAndThrows(MockServer mockServer) {
        // given
        AscendOcrClient client = clientFor(mockServer, expiredPollTimeout());

        // then
        assertThatThrownBy(() -> client.process(PNG_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("did not finish within");
        assertThat(sentMethods).containsExactly(HttpMethod.POST, HttpMethod.GET, HttpMethod.DELETE);
    }

    @Test
    @PactTestFor(pactMethod = "failedWithOcrFailed")
    @DisplayName("process throws on OCR_FAILED without submitting the document again")
    void process_WhenJobFailsWithOcrFailed_ThenThrowsWithoutResubmitting(MockServer mockServer) {
        // given
        AscendOcrClient client = clientFor(mockServer, properties());

        // then
        assertThatThrownBy(() -> client.process(PNG_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("finished as failed [" + CODE_OCR_FAILED + "]");
        assertThat(sentMethods).containsExactly(HttpMethod.POST, HttpMethod.GET);
    }

    @Test
    @PactTestFor(pactMethod = "failedWithServiceRestarted")
    @DisplayName("process submits the document a second time after SERVICE_RESTARTED and then throws")
    void process_WhenJobFailsWithServiceRestarted_ThenSubmitsTwiceAndThrows(MockServer mockServer) {
        // given
        AscendOcrClient client = clientFor(mockServer, properties());

        // then
        assertThatThrownBy(() -> client.process(PNG_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("finished as failed [" + CODE_SERVICE_RESTARTED + "]");
        assertThat(sentMethods)
                .containsExactly(HttpMethod.POST, HttpMethod.GET, HttpMethod.POST, HttpMethod.GET);
    }

    @Test
    @PactTestFor(pactMethod = "failedWithResultStoreUnavailable")
    @DisplayName("process submits the document a second time after RESULT_STORE_UNAVAILABLE and then throws")
    void process_WhenJobFailsWithResultStoreUnavailable_ThenSubmitsTwiceAndThrows(MockServer mockServer) {
        // given
        AscendOcrClient client = clientFor(mockServer, properties());

        // then
        assertThatThrownBy(() -> client.process(PNG_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("finished as failed [" + CODE_RESULT_STORE_UNAVAILABLE + "]");
        assertThat(sentMethods)
                .containsExactly(HttpMethod.POST, HttpMethod.GET, HttpMethod.POST, HttpMethod.GET);
    }

    @Test
    @PactTestFor(pactMethod = "cancelled")
    @DisplayName("process throws when the job was cancelled")
    void process_WhenJobWasCancelled_ThenThrows(MockServer mockServer) {
        // given
        AscendOcrClient client = clientFor(mockServer, properties());

        // then
        assertThatThrownBy(() -> client.process(PNG_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("finished as cancelled");
        assertThat(sentMethods).containsExactly(HttpMethod.POST, HttpMethod.GET);
    }

    @Test
    @PactTestFor(pactMethod = "unknownJobOnRead")
    @DisplayName("process throws when the service no longer knows the job it is reading")
    void process_WhenJobIsUnknownOnRead_ThenThrows(MockServer mockServer) {
        // given
        AscendOcrClient client = clientFor(mockServer, properties());

        // then
        assertThatThrownBy(() -> client.process(PNG_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("Failed to read ascend-ocr job " + JOB_ID)
                .hasCauseInstanceOf(HttpClientErrorException.NotFound.class);
        assertThat(sentMethods).containsExactly(HttpMethod.POST, HttpMethod.GET);
    }

    @Test
    @PactTestFor(pactMethod = "failedDeleteAfterSuccess")
    @DisplayName("process still returns the document when deleting the finished job is refused")
    void process_WhenDeleteAfterSuccessIsRefused_ThenStillReturnsTheDocument(MockServer mockServer) {
        // given
        AscendOcrClient client = clientFor(mockServer, properties());
        stubStoredResult(s3Client, MARKDOWN);

        // when
        List<Document> documents = client.process(PNG_BYTES, FILENAME, null);

        // then
        assertThat(documents).hasSize(1);
        assertThat(documents.getFirst().getText()).isEqualTo(MARKDOWN);
        assertThat(sentMethods).containsExactly(HttpMethod.POST, HttpMethod.GET, HttpMethod.DELETE);
    }

    private AscendOcrClient clientFor(MockServer mockServer, AscendOcrProperties properties) {
        properties.setBaseUrl(mockServer.getUrl());
        RestClient restClient = RestClient.builder()
                .requestFactory(new SimpleClientHttpRequestFactory())
                .requestInterceptor((request, body, execution) -> {
                    sentMethods.add(request.getMethod());

                    return execution.execute(request, body);
                })
                .build();

        return new AscendOcrClient(restClient, new ObjectMapper(), s3Client, properties);
    }

    private void assertFetchedResultFromTheRecordedAddress() {
        ArgumentCaptor<GetObjectRequest> fetched = ArgumentCaptor.forClass(GetObjectRequest.class);
        verify(s3Client).getObjectAsBytes(fetched.capture());
        assertThat(fetched.getValue().bucket()).isEqualTo(BUCKET);
        assertThat(fetched.getValue().key()).isEqualTo(KEY);
    }

    private static AscendOcrProperties expiredPollTimeout() {
        AscendOcrProperties properties = properties();
        properties.setPollTimeout(Duration.ZERO);

        return properties;
    }

    private static PactDslResponse submitPngInEnglish(PactDslWithState state) {
        return acceptedSubmission(state, "a submission of a PNG in English", pngUpload(LANG_ENGLISH));
    }

    private static PactDslResponse submitPngWithoutLanguage(PactDslWithState state) {
        return acceptedSubmission(state, "a submission of a PNG without a language", pngUpload(null));
    }

    private static PactDslResponse acceptedSubmission(
            PactDslWithState state, String description, MultipartEntityBuilder upload) {
        return state.uponReceiving(description)
                .path(JOBS_PATH)
                .method(HttpMethod.POST.name())
                .body(upload)
                .willRespondWith()
                .status(202)
                .matchHeader(HttpHeaders.LOCATION, LOCATION_PATTERN, JOB_PATH)
                .body(new PactDslJsonBody()
                        .stringMatcher("job_id", JOB_ID_PATTERN, JOB_ID)
                        .stringValue("state", "waiting"));
    }

    private static PactDslResponse readSucceededJob(PactDslWithState state) {
        return state.uponReceiving("a status read of a succeeded job")
                .path(JOB_PATH)
                .method(HttpMethod.GET.name())
                .willRespondWith()
                .status(200)
                .body(new PactDslJsonBody()
                        .stringValue("state", "succeeded")
                        .object("result")
                        .stringMatcher("bucket", NON_EMPTY_PATTERN, BUCKET)
                        .stringMatcher("key", NON_EMPTY_PATTERN, KEY)
                        .closeObject());
    }

    private static PactDslResponse readFailedJob(PactDslResponse previous, String errorCode) {
        return previous.given(JOB_HAS_FAILED, failedJobState(errorCode))
                .uponReceiving("a status read of a job that failed with " + errorCode)
                .path(JOB_PATH)
                .method(HttpMethod.GET.name())
                .willRespondWith()
                .status(200)
                .body(new PactDslJsonBody()
                        .stringValue("state", "failed")
                        .stringValue("error_code", errorCode)
                        .stringType("error_reason", "The job failed with " + errorCode));
    }

    private static PactDslResponse deleteSucceededJob(PactDslWithState state) {
        return state.uponReceiving("a delete of a succeeded job")
                .path(JOB_PATH)
                .method(HttpMethod.DELETE.name())
                .willRespondWith()
                .status(204);
    }

    private static PactDslResponse deleteWaitingJob(PactDslWithState state) {
        return state.uponReceiving("a delete of a waiting job")
                .path(JOB_PATH)
                .method(HttpMethod.DELETE.name())
                .willRespondWith()
                .status(204);
    }

    private static PactDslResponse deleteRunningJob(PactDslWithState state) {
        return state.uponReceiving("a delete of a running job")
                .path(JOB_PATH)
                .method(HttpMethod.DELETE.name())
                .willRespondWith()
                .status(204);
    }

    private static Map<String, Object> jobState() {
        Map<String, Object> params = new LinkedHashMap<>();
        params.put(PARAM_JOB_ID, JOB_ID);

        return params;
    }

    private static Map<String, Object> failedJobState(String errorCode) {
        Map<String, Object> params = jobState();
        params.put(PARAM_ERROR_CODE, errorCode);

        return params;
    }

    private static MultipartEntityBuilder pngUpload(String lang) {
        MultipartEntityBuilder upload = MultipartEntityBuilder.create()
                .setBoundary(MULTIPART_BOUNDARY)
                .addPart(filePart(FILENAME, PNG_BYTES, MEDIA_PNG));
        if (lang != null) {
            upload.addPart(langPart(lang));
        }

        return upload;
    }

    private static MultipartEntityBuilder textUpload() {
        return MultipartEntityBuilder.create()
                .setBoundary(MULTIPART_BOUNDARY)
                .addPart(filePart(TEXT_FILENAME, TEXT_BYTES, MEDIA_TEXT));
    }

    private static FormBodyPart filePart(String filename, byte[] bytes, String mediaType) {
        ByteArrayBody content = new ByteArrayBody(bytes, ContentType.create(mediaType), filename);

        return FormBodyPartBuilder.create(PART_FILE, content)
                .addField(CONTENT_DISPOSITION, "form-data; name=\"" + PART_FILE + "\"; filename=\"" + filename + "\"")
                .addField(CONTENT_TYPE, mediaType)
                .build();
    }

    private static FormBodyPart langPart(String lang) {
        StringBody content = new StringBody(lang, ContentType.TEXT_PLAIN.withCharset(StandardCharsets.UTF_8));

        return FormBodyPartBuilder.create(PART_LANG, content)
                .addField(CONTENT_DISPOSITION, "form-data; name=\"" + PART_LANG + "\"")
                .addField(CONTENT_TYPE, MEDIA_TEXT_UTF8)
                .build();
    }

    private static byte[] whitePng() {
        BufferedImage image = new BufferedImage(PNG_SIDE_PIXELS, PNG_SIDE_PIXELS, BufferedImage.TYPE_BYTE_GRAY);
        Arrays.fill(((DataBufferByte) image.getRaster().getDataBuffer()).getData(), WHITE);
        ByteArrayOutputStream png = new ByteArrayOutputStream();

        try {
            ImageIO.write(image, "png", png);

        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }

        return png.toByteArray();
    }
}
