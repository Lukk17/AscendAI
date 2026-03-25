package com.lukk.ascend.ai.orchestrator.service.ingestion;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.orchestrator.exception.IngestionException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.document.Document;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestClient;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Iterator;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class IngestionServiceTest {

    @Mock
    private RestClient restClient;

    @Mock
    private RestClient.RequestBodyUriSpec requestBodyUriSpec;

    @Mock
    private RestClient.RequestBodySpec requestBodySpec;

    @Mock
    private RestClient.ResponseSpec responseSpec;

    @Mock
    private ObjectMapper objectMapper;

    @InjectMocks
    private IngestionService ingestionService;

    @BeforeEach
    void setupGlobalFields() {
        ReflectionTestUtils.setField(ingestionService, "unstructuredBaseUrl", "http://localhost:8000");
        ReflectionTestUtils.setField(ingestionService, "unstructuredApiPath", "/general/v0/general");
    }

    @Test
    void processMarkdown_WhenH1IsPresent_ThenExtractsTitleSuccessfully() {
        // given
        String markdown = "# My Title\nSome content.";
        InputStream inputStream = new ByteArrayInputStream(markdown.getBytes(StandardCharsets.UTF_8));
        String filename = "file.md";

        // when
        List<Document> documents = ingestionService.processMarkdown(inputStream, filename);

        // then
        assertThat(documents).hasSize(1);
        assertThat(documents.get(0).getMetadata()).containsEntry("title", "My Title");
        assertThat(documents.get(0).getMetadata()).containsEntry("source", filename);
    }

    @Test
    void processMarkdown_WhenNoH1Present_ThenUsesFilenameAsTitle() {
        // given
        String markdown = "## Subtitle\nSome content.";
        InputStream inputStream = new ByteArrayInputStream(markdown.getBytes(StandardCharsets.UTF_8));
        String filename = "file.md";

        // when
        List<Document> documents = ingestionService.processMarkdown(inputStream, filename);

        // then
        assertThat(documents).hasSize(1);
        assertThat(documents.get(0).getMetadata()).containsEntry("title", filename);
    }

    @Test
    void processMarkdown_WhenInputStreamThrowsIOException_ThenThrowsIngestionException() throws IOException {
        // given
        InputStream inputStream = mock(InputStream.class);
        when(inputStream.read(any(byte[].class), any(int.class), any(int.class))).thenThrow(new IOException("Disk Error"));

        // when / then
        assertThatThrownBy(() -> ingestionService.processMarkdown(inputStream, "fail.md"))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("Failed to process markdown file");
    }

    @Test
    void processUnstructured_WhenValidApiResponse_ThenParsesAndReturnsDocuments() throws Exception {
        // given
        InputStream inputStream = new ByteArrayInputStream("dummy".getBytes());
        String filename = "file.pdf";
        String jsonResponse = "[{\"text\": \"extracted text\"}]";

        mockRestClientSetup();
        when(responseSpec.body(String.class)).thenReturn(jsonResponse);

        JsonNode mockRootNode = mock(JsonNode.class);
        JsonNode mockTextNode = mock(JsonNode.class);
        when(objectMapper.readTree(jsonResponse)).thenReturn(mockRootNode);
        when(mockRootNode.isArray()).thenReturn(true);
        Iterator<JsonNode> iterator = List.of(mockTextNode).iterator();
        when(mockRootNode.iterator()).thenReturn(iterator);
        when(mockTextNode.has("text")).thenReturn(true);
        when(mockTextNode.get("text")).thenReturn(mockTextNode);
        when(mockTextNode.asText()).thenReturn("extracted text");

        // when
        List<Document> documents = ingestionService.processUnstructured(inputStream, filename);

        // then
        assertThat(documents).hasSize(1);
        assertThat(documents.get(0).getText()).contains("extracted text");
        assertThat(documents.get(0).getMetadata()).containsEntry("type", "unstructured");
    }

    @Test
    void processUnstructured_WhenApiCallThrowsException_ThenWrapsInRuntimeException() {
        // given
        InputStream inputStream = new ByteArrayInputStream("dummy".getBytes());
        String filename = "file.pdf";

        mockRestClientSetup();
        when(responseSpec.body(String.class)).thenThrow(new RuntimeException("API Error"));

        // when / then
        assertThatThrownBy(() -> ingestionService.processUnstructured(inputStream, filename))
                .isInstanceOf(RuntimeException.class);
    }

    @Test
    void processUnstructured_WhenInputStreamThrowsIOException_ThenThrowsIngestionException() throws IOException {
        // given
        InputStream inputStream = mock(InputStream.class);
        when(inputStream.readAllBytes()).thenThrow(new IOException("Stream crash"));

        // when / then
        assertThatThrownBy(() -> ingestionService.processUnstructured(inputStream, "fail.pdf"))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("Failed to read input stream for file: fail.pdf");
    }

    @Test
    void processUnstructured_WhenInvalidJsonResponse_ThenThrowsIngestionException() throws Exception {
        // given
        InputStream inputStream = new ByteArrayInputStream("dummy".getBytes());
        String filename = "file.pdf";
        String jsonResponse = "{ broken";

        mockRestClientSetup();
        when(responseSpec.body(String.class)).thenReturn(jsonResponse);
        when(objectMapper.readTree(jsonResponse)).thenThrow(new JsonProcessingException("Broken json") {});

        // when / then
        assertThatThrownBy(() -> ingestionService.processUnstructured(inputStream, filename))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("Failed to parse Unstructured API response");
    }

    private void mockRestClientSetup() {
        when(restClient.post()).thenReturn(requestBodyUriSpec);
        when(requestBodyUriSpec.uri(anyString())).thenReturn(requestBodySpec);
        when(requestBodySpec.contentType(any())).thenReturn(requestBodySpec);
        when(requestBodySpec.body(any(Object.class))).thenReturn(requestBodySpec);
        when(requestBodySpec.retrieve()).thenReturn(responseSpec);
    }
}
