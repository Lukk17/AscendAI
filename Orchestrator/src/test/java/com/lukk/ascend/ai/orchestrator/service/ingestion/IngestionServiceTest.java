package com.lukk.ascend.ai.orchestrator.service.ingestion;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
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
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Iterator;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class IngestionServiceTest {

    @Mock
    private RestClient.Builder restClientBuilder;

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
    void setUp() {
        ReflectionTestUtils.setField(ingestionService, "unstructuredBaseUrl", "http://localhost:8000");
        ReflectionTestUtils.setField(ingestionService, "unstructuredApiPath", "/general/v0/general");
    }

    @Test
    void processMarkdown_ShouldExtractTitle_WhenH1IsPresent() {
        // given
        String markdown = "# My Title\nSome content.";
        InputStream inputStream = new ByteArrayInputStream(markdown.getBytes(StandardCharsets.UTF_8));
        String filename = "file.md";

        // when
        List<Document> documents = ingestionService.processMarkdown(inputStream, filename);

        // then
        assertNotNull(documents);
        assertEquals(1, documents.size());
        assertEquals("My Title", documents.get(0).getMetadata().get("title"));
        assertEquals(filename, documents.get(0).getMetadata().get("source"));
    }

    @Test
    void processMarkdown_ShouldUseFilenameAsTitle_WhenNoH1Present() {
        // given
        String markdown = "## Subtitle\nSome content.";
        InputStream inputStream = new ByteArrayInputStream(markdown.getBytes(StandardCharsets.UTF_8));
        String filename = "file.md";

        // when
        List<Document> documents = ingestionService.processMarkdown(inputStream, filename);

        // then
        assertEquals(filename, documents.get(0).getMetadata().get("title"));
    }

    @Test
    void processUnstructured_ShouldCallApiAndParseResponse() throws Exception {
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
        assertNotNull(documents);
        assertEquals(1, documents.size());
        assertTrue(documents.get(0).getText().contains("extracted text"));
    }

    @Test
    void processUnstructured_ShouldThrowException_WhenApiCallFails() {
        // given
        InputStream inputStream = new ByteArrayInputStream("dummy".getBytes());
        String filename = "file.pdf";

        mockRestClientSetup();
        when(responseSpec.body(String.class)).thenThrow(new RuntimeException("API Error"));

        // when & then
        assertThrows(RuntimeException.class, () -> ingestionService.processUnstructured(inputStream, filename));
    }

    private void mockRestClientSetup() {
        when(restClientBuilder.build()).thenReturn(restClient);
        when(restClient.post()).thenReturn(requestBodyUriSpec);
        when(requestBodyUriSpec.uri(anyString())).thenReturn(requestBodySpec);
        when(requestBodySpec.contentType(any())).thenReturn(requestBodySpec);
        when(requestBodySpec.body(any(Object.class))).thenReturn(requestBodySpec);
        when(requestBodySpec.retrieve()).thenReturn(responseSpec);
    }
}
