package com.lukk.ascend.ai.agent.service.ingestion.client;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.config.properties.AscendOcrProperties;
import com.lukk.ascend.ai.agent.exception.IngestionException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Named;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.ai.document.Document;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import software.amazon.awssdk.services.s3.S3Client;

import java.util.List;
import java.util.stream.Stream;

import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.FILENAME;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.FILE_BYTES;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.JOBS_URL;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.JOB_ID;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.MARKDOWN;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.cancelledBody;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.expectDelete;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.expectStatus;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.expectSubmit;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.failedBody;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.properties;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.stubStoredResult;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.succeededBody;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.succeededBodyWithNullPollHint;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;

class AscendOcrClientResponseParsingTest {

    private static final String CODE_SERVICE_RESTARTED = "SERVICE_RESTARTED";
    private static final String CODE_RESULT_STORE_UNAVAILABLE = "RESULT_STORE_UNAVAILABLE";
    private static final String CODE_OCR_FAILED = "OCR_FAILED";

    private MockRestServiceServer server;
    private S3Client s3Client;
    private AscendOcrClient client;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder();
        server = MockRestServiceServer.bindTo(builder).build();
        s3Client = mock(S3Client.class);
        AscendOcrProperties properties = properties();
        client = new AscendOcrClient(builder.build(), new ObjectMapper(), s3Client, properties);
    }

    @Test
    @DisplayName("process throws when a status answer is not JSON")
    void process_WhenStatusIsNotJson_ThenThrows() {
        // given
        expectSubmit(server);
        expectStatus(server, "<html>not json</html>");

        // then
        assertThatThrownBy(() -> client.process(FILE_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("Failed to parse ascend-ocr JSON response");
        server.verify();
    }

    @Test
    @DisplayName("process throws when a status answer carries no state")
    void process_WhenStatusHasNoState_ThenThrows() {
        // given
        expectSubmit(server);
        expectStatus(server, "{\"job_id\":\"" + JOB_ID + "\"}");

        // then
        assertThatThrownBy(() -> client.process(FILE_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("reported no state");
        server.verify();
    }

    @Test
    @DisplayName("process keeps polling through a state it does not recognise as terminal")
    void process_WhenStateIsUnknown_ThenKeepsPolling() {
        // given
        expectSubmit(server);
        expectStatus(server, "{\"job_id\":\"" + JOB_ID + "\",\"state\":\"warming-up\"}");
        expectStatus(server, succeededBody());
        expectDelete(server);
        stubStoredResult(s3Client, MARKDOWN);

        // then
        assertThat(client.process(FILE_BYTES, FILENAME, null)).hasSize(1);
        server.verify();
    }

    @Test
    @DisplayName("process throws when a succeeded record carries no result address")
    void process_WhenSucceededWithoutResult_ThenThrows() {
        // given
        expectSubmit(server);
        expectStatus(server, "{\"job_id\":\"" + JOB_ID + "\",\"state\":\"succeeded\"}");

        // then
        assertThatThrownBy(() -> client.process(FILE_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("succeeded without a result address");
        server.verify();
    }

    @Test
    @DisplayName("process throws when a succeeded record names a bucket but no key")
    void process_WhenSucceededWithoutResultKey_ThenThrows() {
        // given
        expectSubmit(server);
        expectStatus(server, "{\"job_id\":\"" + JOB_ID
                + "\",\"state\":\"succeeded\",\"result\":{\"bucket\":\"ocr-results\"}}");

        // then
        assertThatThrownBy(() -> client.process(FILE_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("succeeded without a result address");
        server.verify();
    }

    @Test
    @DisplayName("process throws carrying the record's code and reason when the reading failed")
    void process_WhenRecordFailed_ThenThrowsCarryingCodeAndReason() {
        // given
        expectSubmit(server);
        expectStatus(server, failedBody(CODE_OCR_FAILED, "page 1 could not be read"));

        // then
        assertThatThrownBy(() -> client.process(FILE_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining(CODE_OCR_FAILED)
                .hasMessageContaining("page 1 could not be read");
        server.verify();
    }

    @Test
    @DisplayName("process throws naming the state when a failed record carries no code")
    void process_WhenRecordFailedWithoutCode_ThenThrowsNamingTheState() {
        // given
        expectSubmit(server);
        expectStatus(server, "{\"job_id\":\"" + JOB_ID + "\",\"state\":\"failed\"}");

        // then
        assertThatThrownBy(() -> client.process(FILE_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("finished as failed");
        server.verify();
    }

    @Test
    @DisplayName("process throws when the job was cancelled")
    void process_WhenRecordCancelled_ThenThrows() {
        // given
        expectSubmit(server);
        expectStatus(server, cancelledBody());

        // then
        assertThatThrownBy(() -> client.process(FILE_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("finished as cancelled");
        server.verify();
    }

    @Test
    @DisplayName("process resubmits once when the service restarted, because nothing was learned about the document")
    void process_WhenServiceRestarted_ThenResubmitsOnce() {
        // given
        expectSubmit(server);
        expectStatus(server, failedBody(CODE_SERVICE_RESTARTED, "service restarted while the job was running"));
        expectSubmit(server);
        expectStatus(server, succeededBody());
        expectDelete(server);
        stubStoredResult(s3Client, MARKDOWN);

        // when
        List<Document> documents = client.process(FILE_BYTES, FILENAME, null);

        // then
        assertThat(documents).hasSize(1);
        server.verify();
    }

    @Test
    @DisplayName("process resubmits once when the result store was unavailable")
    void process_WhenResultStoreUnavailable_ThenResubmitsOnce() {
        // given
        expectSubmit(server);
        expectStatus(server, failedBody(CODE_RESULT_STORE_UNAVAILABLE, "result store refused the upload"));
        expectSubmit(server);
        expectStatus(server, succeededBody());
        expectDelete(server);
        stubStoredResult(s3Client, MARKDOWN);

        // then
        assertThat(client.process(FILE_BYTES, FILENAME, null)).hasSize(1);
        server.verify();
    }

    @Test
    @DisplayName("process submits at most twice, so a second retryable failure is not resubmitted again")
    void process_WhenTwoRetryableFailures_ThenSubmitsTwiceAndThrows() {
        // given
        expectSubmit(server);
        expectStatus(server, failedBody(CODE_SERVICE_RESTARTED, "service restarted"));
        expectSubmit(server);
        expectStatus(server, failedBody(CODE_RESULT_STORE_UNAVAILABLE, "result store refused the upload"));

        // then
        assertThatThrownBy(() -> client.process(FILE_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining(CODE_RESULT_STORE_UNAVAILABLE);
        server.verify();
    }

    @Test
    @DisplayName("process never resubmits a document the service could not read")
    void process_WhenOcrFailed_ThenSubmitsOnlyOnce() {
        // given
        expectSubmit(server);
        expectStatus(server, failedBody(CODE_OCR_FAILED, "no text detected"));

        // then
        assertThatThrownBy(() -> client.process(FILE_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining(CODE_OCR_FAILED);
        server.verify();
    }

    @Test
    @DisplayName("process throws when the submission answer carries no job identifier")
    void process_WhenSubmissionCarriesNoJobId_ThenThrows() {
        // given
        server.expect(requestTo(JOBS_URL))
                .andExpect(method(HttpMethod.POST))
                .andRespond(withStatus(HttpStatus.ACCEPTED)
                        .contentType(MediaType.APPLICATION_JSON)
                        .body("{\"state\":\"waiting\"}"));

        // then
        assertThatThrownBy(() -> client.process(FILE_BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("without a job identifier");
        server.verify();
    }

    @ParameterizedTest(name = "{0}")
    @MethodSource("pollHintFieldsCarryingNoHint")
    @DisplayName("process keeps polling at its own floor when a running record's poll hint is missing or null")
    void process_WhenRunningRecordHasNoHint_ThenKeepsPolling(String hintField) {
        // given
        expectSubmit(server);
        expectStatus(server, "{\"job_id\":\"" + JOB_ID + "\",\"state\":\"running\",\"pages_done\":0"
                + hintField + "}");
        expectStatus(server, succeededBody());
        expectDelete(server);
        stubStoredResult(s3Client, MARKDOWN);

        // then
        assertThat(client.process(FILE_BYTES, FILENAME, null)).hasSize(1);
        server.verify();
    }

    @ParameterizedTest(name = "{0}")
    @MethodSource("terminalBodiesWithoutAPollHint")
    @DisplayName("process stops polling a terminal record whether its poll hint is missing or null")
    void process_WhenTerminalRecordHasNoHint_ThenStopsPolling(String terminalBody) {
        // given
        expectSubmit(server);
        expectStatus(server, terminalBody);
        expectDelete(server);
        stubStoredResult(s3Client, MARKDOWN);

        // when
        List<Document> documents = client.process(FILE_BYTES, FILENAME, null);

        // then
        assertThat(documents).hasSize(1);
        server.verify();
    }

    private static Stream<Named<String>> pollHintFieldsCarryingNoHint() {
        return Stream.of(
                Named.of("hint key missing", ""),
                Named.of("hint key null", ",\"poll_after_seconds\":null"));
    }

    private static Stream<Named<String>> terminalBodiesWithoutAPollHint() {
        return Stream.of(
                Named.of("hint key missing", succeededBody()),
                Named.of("hint key null", succeededBodyWithNullPollHint()));
    }
}
