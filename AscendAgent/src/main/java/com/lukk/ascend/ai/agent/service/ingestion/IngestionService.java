package com.lukk.ascend.ai.agent.service.ingestion;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.exception.IngestionException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.commonmark.node.Node;
import org.commonmark.parser.Parser;
import org.commonmark.renderer.text.TextContentRenderer;
import org.springframework.ai.document.Document;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ByteArrayResource;
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

@Service
@RequiredArgsConstructor
@Slf4j
public class IngestionService {

    private static final String TYPE_MARKDOWN = "markdown";
    private static final String TYPE_UNSTRUCTURED = "unstructured";
    private static final String PARAM_FILES = "files";
    private static final String UNSTRUCTURED_TITLE_ELEMENT = "Title";

    // JSON field names in the Unstructured API response — distinct from document-metadata keys
    // even when the literal happens to match (the API returns objects like {"type":"Title","text":"..."}).
    private static final String JSON_TYPE = "type";
    private static final String JSON_TEXT = "text";

    @Qualifier("ingestionRestClient")
    private final RestClient restClient;

    private final ObjectMapper objectMapper;

    @Value("${app.unstructured.base-url}")
    private String unstructuredBaseUrl;

    @Value("${app.unstructured.api-path:/general/v0/general}")
    private String unstructuredApiPath;

    public List<Document> processMarkdown(InputStream inputStream, String filename) {
        log.info("Processing Markdown stream for file: {}", filename);
        try {
            String content = readContentCheckingCharset(inputStream);
            String title = extractTitleFromMarkdown(content);

            if (title == null || title.isBlank()) {
                title = basename(filename);
            }

            String cleanText = renderTextFromMarkdown(content);

            Document doc = new Document(cleanText, Map.of(
                    IngestionMetadataKeys.SOURCE, filename,
                    IngestionMetadataKeys.TITLE, title,
                    IngestionMetadataKeys.TYPE, TYPE_MARKDOWN));

            return List.of(doc);
        } catch (IOException e) {
            log.error("Failed to process markdown file: {}", filename, e);
            throw new IngestionException("Failed to process markdown file: " + filename, e);
        }
    }

    public List<Document> processUnstructured(InputStream inputStream, String filename) {
        log.info("Processing Unstructured stream for file: {}", filename);

        try {
            byte[] content = StreamUtils.copyToByteArray(inputStream);

            MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
            body.add(PARAM_FILES, new ByteArrayResource(content) {
                @Override
                public String getFilename() {
                    return filename;
                }
            });

            String response = restClient.post()
                    .uri(unstructuredBaseUrl + unstructuredApiPath)
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(body)
                    .retrieve()
                    .body(String.class);

            return parseUnstructuredResponse(response, filename);
        } catch (IOException e) {
            throw new IngestionException("Failed to read input stream for file: " + filename, e);
        }
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

    private static String basename(String key) {
        int slash = key.lastIndexOf('/');
        return slash >= 0 ? key.substring(slash + 1) : key;
    }

    private List<Document> parseUnstructuredResponse(String jsonResponse, String filename) {
        List<Document> documents = new ArrayList<>();
        try {
            JsonNode rootNode = objectMapper.readTree(jsonResponse);
            if (rootNode.isArray()) {
                StringBuilder fullText = new StringBuilder();
                String extractedTitle = null;
                for (JsonNode node : rootNode) {
                    if (extractedTitle == null
                            && node.has(JSON_TYPE)
                            && UNSTRUCTURED_TITLE_ELEMENT.equals(node.get(JSON_TYPE).asText())
                            && node.has(JSON_TEXT)) {
                        String candidate = node.get(JSON_TEXT).asText();
                        if (candidate != null && !candidate.isBlank()) {
                            extractedTitle = candidate;
                        }
                    }
                    if (node.has(JSON_TEXT)) {
                        fullText.append(node.get(JSON_TEXT).asText()).append("\n");
                    }
                }

                if (!fullText.isEmpty()) {
                    String title = (extractedTitle != null) ? extractedTitle : basename(filename);
                    Document doc = new Document(fullText.toString(), Map.of(
                            IngestionMetadataKeys.SOURCE, filename,
                            IngestionMetadataKeys.TITLE, title,
                            IngestionMetadataKeys.TYPE, TYPE_UNSTRUCTURED));
                    documents.add(doc);
                }
            }
        } catch (JsonProcessingException e) {
            throw new IngestionException("Failed to parse Unstructured API response", e);
        }
        return documents;
    }

}
