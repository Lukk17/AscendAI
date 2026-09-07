package com.lukk.ascend.ai.agent.service.ingestion.client;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.ai.document.Document;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.mock.http.client.MockClientHttpRequest;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Objects;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class AscendOcrClientLiveContractTest {

    private static final String BASE_URL = "http://localhost:7022";
    private static final String API_PATH = "/v1/ocr";

    // Captured live from a running ascend-ocr instance so these assertions are pinned to what the
    // service actually publishes, not to a guess. Regenerate with:
    //   curl http://localhost:7022/openapi.json > src/test/resources/ascend-ocr/openapi-contract.json
    //   curl -F "file=@apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1-polish.png" \
    //        http://localhost:7022/v1/ocr > src/test/resources/ascend-ocr/real-ocr-response.json
    private static final String OPENAPI_CONTRACT_RESOURCE = "/ascend-ocr/openapi-contract.json";
    private static final String REAL_OCR_RESPONSE_RESOURCE = "/ascend-ocr/real-ocr-response.json";

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    @DisplayName("process sends the multipart part name and query param name ascend-ocr's own OpenAPI contract requires")
    void process_SendsPartAndQueryParamNamesFromRealContract() throws IOException {
        JsonNode contract = readJsonResource(OPENAPI_CONTRACT_RESOURCE);
        String requiredFieldName = contract
                .at("/components/schemas/Body_process_ocr_v1_ocr_post/required/0").asText();
        JsonNode langParam = contract.at("/paths/~1v1~1ocr/post/parameters/0");
        assertThat(langParam.at("/in").asText()).isEqualTo("query");
        String queryParamName = langParam.at("/name").asText();

        RestClient.Builder builder = RestClient.builder();
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        AscendOcrClient client = new AscendOcrClient(builder.build(), objectMapper, BASE_URL, API_PATH);

        server.expect(requestTo(BASE_URL + API_PATH + "?" + queryParamName + "=pl"))
                .andExpect(method(HttpMethod.POST))
                .andExpect(request -> {
                    String rawBody = new String(
                            ((MockClientHttpRequest) request).getBodyAsBytes(), StandardCharsets.ISO_8859_1);
                    assertThat(rawBody).contains("name=\"" + requiredFieldName + "\"");
                })
                .andRespond(withSuccess("{}", MediaType.APPLICATION_JSON));

        client.process("bytes".getBytes(StandardCharsets.UTF_8), "invoice.png", "pl");

        server.verify();
    }

    @Test
    @DisplayName("process extracts real OCR text from a response recorded from the live service")
    void process_ParsesResponseRecordedFromLiveService() throws IOException {
        String realResponseJson = readResourceAsString(REAL_OCR_RESPONSE_RESOURCE);

        RestClient.Builder builder = RestClient.builder();
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        AscendOcrClient client = new AscendOcrClient(builder.build(), objectMapper, BASE_URL, API_PATH);

        server.expect(requestTo(BASE_URL + API_PATH))
                .andExpect(method(HttpMethod.POST))
                .andRespond(withSuccess(realResponseJson, MediaType.APPLICATION_JSON));

        List<Document> result = client.process(
                "bytes".getBytes(StandardCharsets.UTF_8), "argent-saga-chronicles-page1-polish.png", null);

        assertThat(result).hasSize(1);
        assertThat(result.getFirst().getText())
                .contains("Aenaria")
                .contains("Halen Veyr");
        server.verify();
    }

    private JsonNode readJsonResource(String resource) throws IOException {
        try (InputStream stream = getClass().getResourceAsStream(resource)) {
            return objectMapper.readTree(Objects.requireNonNull(stream, resource));
        }
    }

    private String readResourceAsString(String resource) throws IOException {
        try (InputStream stream = getClass().getResourceAsStream(resource)) {
            return new String(Objects.requireNonNull(stream, resource).readAllBytes(), StandardCharsets.UTF_8);
        }
    }
}
