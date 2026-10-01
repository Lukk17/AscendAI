package com.lukk.ascend.ai.agent.service.ingestion.client;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.ai.document.Document;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.mock.http.client.MockClientHttpRequest;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import software.amazon.awssdk.services.s3.S3Client;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Objects;

import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.JOBS_URL;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.acceptedBody;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.expectDelete;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.expectStatus;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.properties;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.stubStoredResult;
import static com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrJobFixtures.succeededBody;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;

class AscendOcrClientLiveContractTest {

    private static final String SOURCE_FILENAME = "argent-saga-chronicles-page1-polish.png";
    private static final String RECORDED_RESULT_RESOURCE = "/ascend-ocr/real-ocr-result.md";

    private final ObjectMapper objectMapper = new ObjectMapper();

    private MockRestServiceServer server;
    private S3Client s3Client;
    private AscendOcrClient client;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder();
        server = MockRestServiceServer.bindTo(builder).build();
        s3Client = mock(S3Client.class);
        client = new AscendOcrClient(builder.build(), objectMapper, s3Client, properties());
    }

    @Test
    @DisplayName("process submits file and lang as multipart form fields on the job endpoint")
    void process_SendsFileAndLangAsMultipartFormFieldsToTheJobEndpoint() throws IOException {
        // given
        expectSubmissionAsserting(rawBody -> {
            assertThat(rawBody).contains("name=\"file\"");
            assertThat(rawBody).contains("name=\"lang\"");
            assertThat(rawBody).contains("pl");
        });
        expectStatus(server, succeededBody());
        expectDelete(server);
        stubStoredResult(s3Client, readRecordedResult());

        // when
        client.process("bytes".getBytes(StandardCharsets.UTF_8), SOURCE_FILENAME, "pl");

        // then
        server.verify();
    }

    @Test
    @DisplayName("process indexes the Markdown result, carrying text recorded from the live service")
    void process_IndexesTheMarkdownResultOfTextRecordedFromTheLiveService() throws IOException {
        // given
        String markdown = readRecordedResult();
        expectSubmissionAsserting(rawBody -> assertThat(rawBody).contains("name=\"file\""));
        expectStatus(server, succeededBody());
        expectDelete(server);
        stubStoredResult(s3Client, markdown);

        // when
        List<Document> result = client.process(
                "bytes".getBytes(StandardCharsets.UTF_8), SOURCE_FILENAME, null);

        // then
        assertThat(result).hasSize(1);
        assertThat(result.getFirst().getText())
                .isEqualTo(markdown)
                .contains("## Page 1")
                .contains("Aenaria")
                .contains("Halen Veyr");
        server.verify();
    }

    private void expectSubmissionAsserting(RawBodyAssertion assertion) {
        server.expect(requestTo(JOBS_URL))
                .andExpect(method(HttpMethod.POST))
                .andExpect(request -> assertion.check(new String(
                        ((MockClientHttpRequest) request).getBodyAsBytes(), StandardCharsets.ISO_8859_1)))
                .andRespond(withStatus(HttpStatus.ACCEPTED)
                        .contentType(MediaType.APPLICATION_JSON)
                        .body(acceptedBody()));
    }

    private String readRecordedResult() throws IOException {
        try (InputStream stream = getClass().getResourceAsStream(RECORDED_RESULT_RESOURCE)) {
            byte[] storedObject = Objects.requireNonNull(stream, RECORDED_RESULT_RESOURCE).readAllBytes();

            return new String(storedObject, StandardCharsets.UTF_8);
        }
    }

    @FunctionalInterface
    private interface RawBodyAssertion {

        void check(String rawBody);
    }
}
