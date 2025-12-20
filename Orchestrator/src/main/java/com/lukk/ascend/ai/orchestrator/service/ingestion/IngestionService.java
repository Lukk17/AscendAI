package com.lukk.ascend.ai.orchestrator.service.ingestion;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.orchestrator.exception.IngestionException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.commonmark.node.Node;
import org.commonmark.parser.Parser;
import org.commonmark.renderer.text.TextContentRenderer;
import org.springframework.ai.document.Document;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.util.StreamUtils;
import org.springframework.web.client.RestClient;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Service responsible for processing raw input streams into AI Documents.
 * <p>
 * This service handles parsing of Markdown files locally and orchestrates
 * the conversion of other formats (PDF, DOCX, etc.) via the Unstructured API.
 * </p>
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class IngestionService {

    private static final String TYPE_MARKDOWN = "markdown";
    private static final String TYPE_UNSTRUCTURED = "unstructured";
    private static final String KEY_SOURCE = "source";
    private static final String KEY_TITLE = "title";
    private static final String KEY_TYPE = "type";
    private static final String KEY_TEXT = "text";
    private static final String PARAM_FILES = "files";

    private final RestClient.Builder restClientBuilder;
    private final ObjectMapper objectMapper;

    @Value("${app.unstructured.base-url}")
    private String unstructuredBaseUrl;

    @Value("${app.unstructured.api-path:/general/v0/general}")
    private String unstructuredApiPath;

    /**
     * Processes a Markdown input stream and converts it into a list of Documents.
     * <p>
     * This method reads the stream, parses the Markdown to extract text content,
     * attempts to find a title from the first H1 heading, and creates a Document
     * with appropriate metadata.
     * </p>
     *
     * @param inputStream The input stream containing Markdown content.
     * @param filename    The name of the source file.
     * @return A list containing the single processed Document.
     * @throws RuntimeException If reading or parsing fails.
     */
    public List<Document> processMarkdown(InputStream inputStream, String filename) {
        log.info("Processing Markdown stream for file: {}", filename);
        try {
            String content = readContentCheckingCharset(inputStream);
            String title = extractTitleFromMarkdown(content);

            if (title == null || title.isBlank()) {
                title = filename;
            }

            String cleanText = renderTextFromMarkdown(content);

            Document doc = new Document(cleanText, Map.of(
                    KEY_SOURCE, filename,
                    KEY_TITLE, title,
                    KEY_TYPE, TYPE_MARKDOWN));

            return List.of(doc);
        } catch (IOException e) {
            log.error("Failed to process markdown file: {}", filename, e);
            throw new IngestionException("Failed to process markdown file: " + filename, e);
        }
    }

    /**
     * Processes a binary input stream (PDF, etc.) using the Unstructured API.
     *
     * @param inputStream The input stream of the file.
     * @param filename    The name of the file.
     * @return A list of Documents extracted from the file.
     */
    public List<Document> processUnstructured(InputStream inputStream, String filename) {
        log.info("Processing Unstructured stream for file: {}", filename);

        RestClient restClient = restClientBuilder.build();

        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add(PARAM_FILES, new MultipartInputStreamResource(inputStream, filename));

        String response = restClient.post()
                .uri(unstructuredBaseUrl + unstructuredApiPath)
                .contentType(MediaType.MULTIPART_FORM_DATA)
                .body(body)
                .retrieve()
                .body(String.class);

        return parseUnstructuredResponse(response, filename);
    }

    private String readContentCheckingCharset(InputStream inputStream) throws IOException {
        return StreamUtils.copyToString(inputStream, StandardCharsets.UTF_8);
    }

    private String renderTextFromMarkdown(String markdownContent) {
        Parser parser = Parser.builder().build();
        Node document = parser.parse(markdownContent);
        TextContentRenderer renderer = TextContentRenderer.builder().build();
        return renderer.render(document);
    }

    private String extractTitleFromMarkdown(String markdownContent) {
        Parser parser = Parser.builder().build();
        Node document = parser.parse(markdownContent);

        TitleExtractionVisitor visitor = new TitleExtractionVisitor();
        document.accept(visitor);
        return visitor.getTitle();
    }

    private List<Document> parseUnstructuredResponse(String jsonResponse, String filename) {
        List<Document> documents = new ArrayList<>();
        try {
            JsonNode rootNode = objectMapper.readTree(jsonResponse);
            if (rootNode.isArray()) {
                StringBuilder fullText = new StringBuilder();
                for (JsonNode node : rootNode) {
                    if (node.has(KEY_TEXT)) {
                        fullText.append(node.get(KEY_TEXT).asText()).append("\n");
                    }
                }

                if (!fullText.isEmpty()) {
                    Document doc = new Document(fullText.toString(), Map.of(
                            KEY_SOURCE, filename,
                            KEY_TYPE, TYPE_UNSTRUCTURED));
                    documents.add(doc);
                }
            }
        } catch (JsonProcessingException e) {
            throw new IngestionException("Failed to parse Unstructured API response", e);
        }
        return documents;
    }

}
