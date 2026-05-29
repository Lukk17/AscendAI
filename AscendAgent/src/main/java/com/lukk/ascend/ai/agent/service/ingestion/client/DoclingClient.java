package com.lukk.ascend.ai.agent.service.ingestion.client;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.exception.IngestionException;
import com.lukk.ascend.ai.agent.service.ingestion.IngestionMetadataKeys;
import com.lukk.ascend.ai.agent.util.NamedByteArrayResource;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.document.Document;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

@Slf4j
@Component
public class DoclingClient {

    private static final String TYPE_DOCLING = "docling";
    // Docling's /v1/convert/file endpoint binds the multipart field to "files" (plural) —
    // the path segment is "file" (singular), but the form field is "files" because the
    // endpoint supports multi-file batches. Sending "file" returns HTTP 422
    // {"type":"missing","loc":["body","files"],"msg":"Field required"}.
    private static final String PARAM_FILE = "files";

    private static final String JSON_DOCUMENT = "document";
    private static final String JSON_TEXT = "text";
    private static final String[] DOCUMENT_CONTENT_FIELDS = {"md_content", "text_content", "html_content"};

    private static final String LEGACY_PATH = "/v1/convert";
    private static final String CORRECT_PATH = "/v1/convert/file";

    private final RestClient restClient;
    private final ObjectMapper objectMapper;
    private final String doclingBaseUrl;
    private final String doclingApiPath;

    public DoclingClient(
            @Qualifier("ingestionRestClient") RestClient restClient,
            ObjectMapper objectMapper,
            @Value("${app.docling.base-url:http://localhost:5001}") String doclingBaseUrl,
            @Value("${app.docling.api-path:/v1/convert/file}") String doclingApiPath) {
        this.restClient = restClient;
        this.objectMapper = objectMapper;
        this.doclingBaseUrl = doclingBaseUrl;
        this.doclingApiPath = normalizePath(doclingApiPath);
    }

    private static String normalizePath(String configured) {
        if (configured == null) {
            return CORRECT_PATH;
        }
        String trimmed = configured.trim();
        if (!trimmed.startsWith("/")) {
            trimmed = "/" + trimmed;
        }
        if (trimmed.length() > 1 && trimmed.endsWith("/")) {
            trimmed = trimmed.substring(0, trimmed.length() - 1);
        }
        if (LEGACY_PATH.equals(trimmed)) {
            log.warn("[DoclingClient] Configured api-path '{}' is the legacy convert endpoint; auto-correcting to '{}'. " +
                    "Update app.docling.api-path in application.yaml to silence this warning.", configured, CORRECT_PATH);
            return CORRECT_PATH;
        }
        return trimmed;
    }

    @PostConstruct
    void logConfiguredEndpoint() {
        log.info("[DoclingClient] Configured upload endpoint: {}{}", doclingBaseUrl, doclingApiPath);
    }

    public List<Document> process(byte[] fileBytes, String filename) {
        log.info("[DoclingClient] Sending file to Docling: {}", filename);

        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add(PARAM_FILE, new NamedByteArrayResource(fileBytes, filename));

        try {
            String response = restClient.post()
                    .uri(doclingBaseUrl + doclingApiPath + "?to_formats=json")
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(body)
                    .retrieve()
                    .body(String.class);
            return parseResponse(response, filename);
        } catch (RestClientException e) {
            throw new IngestionException("Failed to process document with Docling: " + filename, e);
        }
    }

    private List<Document> parseResponse(String jsonResponse, String filename) {
        List<Document> documents = new ArrayList<>();
        try {
            JsonNode rootNode = objectMapper.readTree(jsonResponse);
            String extracted = extractDoclingContent(rootNode);

            if (extracted.isBlank()) {
                log.warn("[DoclingClient] Empty extraction for {} - response payload top-level keys: {}",
                        filename, rootNode.fieldNames());
            } else {
                log.info("[DoclingClient] Extracted {} characters from {}", extracted.length(), filename);
                documents.add(new Document(extracted, Map.of(
                        IngestionMetadataKeys.SOURCE, filename,
                        IngestionMetadataKeys.TYPE, TYPE_DOCLING)));
            }
        } catch (JsonProcessingException e) {
            throw new IngestionException("Failed to parse Docling JSON response", e);
        }
        return documents;
    }

    /**
     * Docling Serve's /v1/convert/file with to_formats=json returns
     * { "status": "success", "document": { "md_content": "...", "text_content": "...",
     * "json_content": {...}, "html_content": "..." }, ... }
     * Earlier versions of the agent walked the tree for "text" keys, which matched an older
     * (Docling Core) response shape where each text item was {"text": "..."}. The newer
     * Docling Serve response stores the full rendering as a single string on document.md_content
     * (or .text_content), so the old walker silently extracted nothing.
     */
    private String extractDoclingContent(JsonNode rootNode) {
        JsonNode documentNode = rootNode.path(JSON_DOCUMENT);
        for (String field : DOCUMENT_CONTENT_FIELDS) {
            JsonNode candidate = documentNode.path(field);
            if (candidate.isTextual() && !candidate.asText().isBlank()) {
                return candidate.asText();
            }
        }

        StringBuilder fallback = new StringBuilder();
        walkForTextKeys(rootNode, fallback);

        return fallback.toString();
    }

    private void walkForTextKeys(JsonNode node, StringBuilder sb) {
        if (node.isObject()) {
            if (node.has(JSON_TEXT) && node.get(JSON_TEXT).isTextual()) {
                sb.append(node.get(JSON_TEXT).asText()).append("\n");
            }
            node.elements().forEachRemaining(child -> walkForTextKeys(child, sb));
            return;
        }
        if (node.isArray()) {
            node.elements().forEachRemaining(child -> walkForTextKeys(child, sb));
        }
    }
}
