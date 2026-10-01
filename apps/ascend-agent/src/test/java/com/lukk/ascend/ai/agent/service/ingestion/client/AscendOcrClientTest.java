package com.lukk.ascend.ai.agent.service.ingestion.client;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.config.properties.AscendOcrProperties;
import com.lukk.ascend.ai.agent.exception.IngestionException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.ai.document.Document;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.mock.http.client.MockClientHttpRequest;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import software.amazon.awssdk.core.ResponseBytes;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;
import software.amazon.awssdk.services.s3.model.GetObjectResponse;
import software.amazon.awssdk.services.s3.model.NoSuchKeyException;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.BUCKET;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.FILENAME;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.FILE_BYTES;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.JOBS_PATH;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.JOBS_URL;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.JOB_URL;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.KEY;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.MARKDOWN;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.acceptedBody;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.expectDelete;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.expectStatus;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.expectSubmit;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.properties;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.queueFullBody;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.runningBody;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.stubStoredResult;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.succeededBody;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.client.ExpectedCount.times;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withNoContent;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class AscendOcrClientTest {

    private MockRestServiceServer server;
    private S3Client s3Client;
    private AscendOcrProperties properties;
    private AscendOcrClient client;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder();
        server = MockRestServiceServer.bindTo(builder).build();
        s3Client = mock(S3Client.class);
        properties = properties();
        client = new AscendOcrClient(builder.build(), new ObjectMapper(), s3Client, properties);
    }

    @Test
    @DisplayName("process submits the document, polls until it succeeds, fetches the result and deletes the job")
    void process_WhenJobSucceeds_ThenSubmitsPollsFetchesAndDeletes() {
        // given
        expectSubmit(server);
        expectStatus(server, runningBody(0.001));
        expectStatus(server, succeededBody());
        expectDelete(server);
        stubStoredResult(s3Client, MARKDOWN);

        // when
        List<Document> documents = client.process(FILE_BYTES, FILENAME, "en");

        // then
        assertThat(documents).hasSize(1);
        assertThat(documents.getFirst().getText()).isEqualTo(MARKDOWN);
        assertThat(documents.getFirst().getMetadata())
                .containsEntry("source", FILENAME)
                .containsEntry("type", "ascendocr");

        ArgumentCaptor<GetObjectRequest> fetched = ArgumentCaptor.forClass(GetObjectRequest.class);
        verify(s3Client).getObjectAsBytes(fetched.capture());
        assertThat(fetched.getValue().bucket()).isEqualTo(BUCKET);
        assertThat(fetched.getValue().key()).isEqualTo(KEY);

        server.verify();
    }

    @Test
    @DisplayName("process sends the document and its language as multipart form fields on the job endpoint")
    void process_WhenSubmitting_ThenSendsFileAndLangAsMultipartFields() {
        // given
        server.expect(requestTo(JOBS_URL))
                .andExpect(method(HttpMethod.POST))
                .andExpect(request -> {
                    String rawBody = new String(
                            ((MockClientHttpRequest) request).getBodyAsBytes(), StandardCharsets.ISO_8859_1);
                    assertThat(rawBody).contains("name=\"file\"");
                    assertThat(rawBody).contains("name=\"lang\"");
                    assertThat(rawBody).contains("pl");
                })
                .andRespond(withStatus(HttpStatus.ACCEPTED)
                        .contentType(MediaType.APPLICATION_JSON)
                        .body(acceptedBody()));
        expectStatus(server, succeededBody());
        expectDelete(server);
        stubStoredResult(s3Client, MARKDOWN);

        // when
        client.process(FILE_BYTES, FILENAME, "pl");

        // then
        server.verify();
    }

    @Test
    @DisplayName("process omits the language field when no language is given")
    void process_WhenLangIsBlank_ThenOmitsLangField() {
        // given
        server.expect(requestTo(JOBS_URL))
                .andExpect(method(HttpMethod.POST))
                .andExpect(request -> {
                    String rawBody = new String(
                            ((MockClientHttpRequest) request).getBodyAsBytes(), StandardCharsets.ISO_8859_1);
                    assertThat(rawBody).doesNotContain("name=\"lang\"");
                })
                .andRespond(withStatus(HttpStatus.ACCEPTED)
                        .contentType(MediaType.APPLICATION_JSON)
                        .body(acceptedBody()));
        expectStatus(server, succeededBody());
        expectDelete(server);
        stubStoredResult(s3Client, MARKDOWN);

        // when
        client.process(FILE_BYTES, FILENAME, null);

        // then
        server.verify();
    }

    @Test
    @DisplayName("process throws when the submission is answered with anything other than 202 Accepted")
    void process_WhenSubmissionIsNotAccepted_ThenThrows() {
        // given
        server.expect(requestTo(JOBS_URL))
                .andExpect(method(HttpMethod.POST))
                .andRespond(withSuccess(acceptedBody(), MediaType.APPLICATION_JSON));

        // then
        assertThatThrownBy(() -> client.process(FILE_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("answered 200 instead of 202");
        server.verify();
    }

    @Test
    @DisplayName("process throws when the Location header names a job other than the one in the body")
    void process_WhenLocationNamesAnotherJob_ThenThrows() {
        // given
        server.expect(requestTo(JOBS_URL))
                .andExpect(method(HttpMethod.POST))
                .andRespond(withStatus(HttpStatus.ACCEPTED)
                        .contentType(MediaType.APPLICATION_JSON)
                        .header(HttpHeaders.LOCATION, JOBS_PATH + "/some-other-job")
                        .body(acceptedBody()));

        // then
        assertThatThrownBy(() -> client.process(FILE_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("pointed Location at");
        server.verify();
    }

    @Test
    @DisplayName("process still returns the document when deleting the finished job fails")
    void process_WhenDeleteFails_ThenStillReturnsTheDocument() {
        // given
        expectSubmit(server);
        expectStatus(server, succeededBody());
        server.expect(requestTo(JOB_URL))
                .andExpect(method(HttpMethod.DELETE))
                .andRespond(withServerError());
        stubStoredResult(s3Client, MARKDOWN);

        // when
        List<Document> documents = client.process(FILE_BYTES, FILENAME, null);

        // then
        assertThat(documents).hasSize(1);
        server.verify();
    }

    @Test
    @DisplayName("process throws naming the bucket and key when the stored result cannot be fetched")
    void process_WhenResultObjectCannotBeFetched_ThenThrows() {
        // given
        expectSubmit(server);
        expectStatus(server, succeededBody());
        when(s3Client.getObjectAsBytes(any(GetObjectRequest.class)))
                .thenThrow(NoSuchKeyException.builder().message("no such key").build());

        // then
        assertThatThrownBy(() -> client.process(FILE_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining(BUCKET + "/" + KEY);
        server.verify();
    }

    @Test
    @DisplayName("process returns no documents when the stored result holds no text")
    void process_WhenResultIsBlank_ThenReturnsNoDocuments() {
        // given
        expectSubmit(server);
        expectStatus(server, succeededBody());
        expectDelete(server);
        stubStoredResult(s3Client, "");

        // then
        assertThat(client.process(FILE_BYTES, FILENAME, null)).isEmpty();
        server.verify();
    }

    @Test
    @DisplayName("process waits at least the configured floor when the service asks it to poll sooner")
    void process_WhenPollHintIsBelowTheFloor_ThenWaitsTheFloor() {
        // given
        properties.setPollMinInterval(Duration.ofMillis(120));
        properties.setPollMaxInterval(Duration.ofMillis(300));
        expectSubmit(server);
        expectStatus(server, runningBody(0.001));
        expectStatus(server, succeededBody());
        expectDelete(server);
        stubStoredResult(s3Client, MARKDOWN);

        // when
        long startedAt = System.nanoTime();
        client.process(FILE_BYTES, FILENAME, null);
        Duration elapsed = Duration.ofNanos(System.nanoTime() - startedAt);

        // then
        assertThat(elapsed).isGreaterThanOrEqualTo(Duration.ofMillis(120));
        server.verify();
    }

    @Test
    @DisplayName("process waits no longer than the configured cap when the service asks it to poll later")
    void process_WhenPollHintIsAboveTheCap_ThenWaitsNoLongerThanTheCap() {
        // given
        properties.setPollMinInterval(Duration.ofMillis(1));
        properties.setPollMaxInterval(Duration.ofMillis(50));
        expectSubmit(server);
        expectStatus(server, runningBody(600));
        expectStatus(server, succeededBody());
        expectDelete(server);
        stubStoredResult(s3Client, MARKDOWN);

        // when
        long startedAt = System.nanoTime();
        client.process(FILE_BYTES, FILENAME, null);
        Duration elapsed = Duration.ofNanos(System.nanoTime() - startedAt);

        // then
        assertThat(elapsed).isLessThan(Duration.ofSeconds(5));
        server.verify();
    }

    @Test
    @DisplayName("process does every call on the calling thread, so no thread beyond the router pool is created")
    void process_WhenPolling_ThenStaysOnTheCallingThread() {
        // given
        Set<Thread> threads = ConcurrentHashMap.newKeySet();
        server.expect(requestTo(JOBS_URL))
                .andExpect(method(HttpMethod.POST))
                .andExpect(request -> threads.add(Thread.currentThread()))
                .andRespond(withStatus(HttpStatus.ACCEPTED)
                        .contentType(MediaType.APPLICATION_JSON)
                        .body(acceptedBody()));
        server.expect(requestTo(JOB_URL))
                .andExpect(method(HttpMethod.GET))
                .andExpect(request -> threads.add(Thread.currentThread()))
                .andRespond(withSuccess(runningBody(0.001), MediaType.APPLICATION_JSON));
        server.expect(requestTo(JOB_URL))
                .andExpect(method(HttpMethod.GET))
                .andExpect(request -> threads.add(Thread.currentThread()))
                .andRespond(withSuccess(succeededBody(), MediaType.APPLICATION_JSON));
        server.expect(requestTo(JOB_URL))
                .andExpect(method(HttpMethod.DELETE))
                .andExpect(request -> threads.add(Thread.currentThread()))
                .andRespond(withNoContent());
        when(s3Client.getObjectAsBytes(any(GetObjectRequest.class))).thenAnswer(invocation -> {
            threads.add(Thread.currentThread());

            return ResponseBytes.fromByteArray(GetObjectResponse.builder().build(),
                    MARKDOWN.getBytes(StandardCharsets.UTF_8));
        });

        // when
        client.process(FILE_BYTES, FILENAME, null);

        // then
        assertThat(threads).containsExactly(Thread.currentThread());
        server.verify();
    }

    @Test
    @DisplayName("process deletes the job exactly once and throws when its own poll timeout expires")
    void process_WhenPollTimeoutExpires_ThenDeletesTheJobOnceAndThrows() {
        // given
        properties.setPollTimeout(Duration.ZERO);
        expectSubmit(server);
        expectStatus(server, runningBody(0.001));
        expectDelete(server);

        // then
        assertThatThrownBy(() -> client.process(FILE_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("did not finish within");
        server.verify();
    }

    @Test
    @DisplayName("process retries a queue-full refusal up to the configured attempts and then carries its code out")
    void process_WhenQueueIsFull_ThenRetriesUpToTheConfiguredAttempts() {
        // given - Retry-After is far above the configured cap, so the cap is what the client waits
        server.expect(times(3), requestTo(JOBS_URL))
                .andExpect(method(HttpMethod.POST))
                .andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE)
                        .contentType(MediaType.APPLICATION_JSON)
                        .header(HttpHeaders.RETRY_AFTER, "100")
                        .body(queueFullBody()));

        // when
        long startedAt = System.nanoTime();

        // then
        assertThatThrownBy(() -> client.process(FILE_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("QUEUE_FULL")
                .hasMessageContaining("503");
        assertThat(Duration.ofNanos(System.nanoTime() - startedAt)).isLessThan(Duration.ofSeconds(5));
        server.verify();
    }

    @Test
    @DisplayName("process completes normally when a queue-full refusal is followed by an accepted submission")
    void process_WhenQueueClearsAfterARefusal_ThenTheRetriedSubmissionSucceeds() {
        // given
        server.expect(requestTo(JOBS_URL))
                .andExpect(method(HttpMethod.POST))
                .andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE)
                        .contentType(MediaType.APPLICATION_JSON)
                        .header(HttpHeaders.RETRY_AFTER, "0")
                        .body(queueFullBody()));
        expectSubmit(server);
        expectStatus(server, succeededBody());
        expectDelete(server);
        stubStoredResult(s3Client, MARKDOWN);

        // then
        assertThat(client.process(FILE_BYTES, FILENAME, null)).hasSize(1);
        server.verify();
    }

    @Test
    @DisplayName("process never retries a submission that failed on the transport, because the job may exist")
    void process_WhenSubmissionTimesOut_ThenDoesNotRetry() {
        // given
        server.expect(requestTo(JOBS_URL))
                .andExpect(method(HttpMethod.POST))
                .andRespond(request -> {
                    throw new IOException("Read timed out");
                });

        // then
        assertThatThrownBy(() -> client.process(FILE_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("Failed to submit document to ascend-ocr");
        server.verify();
    }

    @Test
    @DisplayName("process never retries a refusal that is not a queue-full refusal")
    void process_WhenRefusedWithAnotherStatus_ThenDoesNotRetry() {
        // given
        server.expect(requestTo(JOBS_URL))
                .andExpect(method(HttpMethod.POST))
                .andRespond(withServerError());

        // then
        assertThatThrownBy(() -> client.process(FILE_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("refused " + FILENAME + " with status 500");
        server.verify();
    }
}
