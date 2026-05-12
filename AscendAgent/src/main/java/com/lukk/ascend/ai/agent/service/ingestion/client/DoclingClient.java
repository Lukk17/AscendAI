package com.lukk.ascend.ai.agent.service.ingestion.client;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.exception.IngestionException;
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
    private static final String KEY_SOURCE = "source";
    private static final String KEY_TYPE = "type";
    // Docling's /v1/convert/file endpoint binds the multipart field to "files" (plural) —
    // the path segment is "file" (singular) but the form field is "files" because the
    // endpoint supports multi-file batches. Sending "file" returns HTTP 422
    // {"type":"missing","loc":["body","files"],"msg":"Field required"}.
    private static final String PARAM_FILE = "files";

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
            StringBuilder fullText = new StringBuilder();
            extractTextRecursive(rootNode, fullText);

            if (!fullText.isEmpty()) {
                documents.add(new Document(fullText.toString(), Map.of(
                        KEY_SOURCE, filename,
                        KEY_TYPE, TYPE_DOCLING)));
            }
        } catch (JsonProcessingException e) {
            throw new IngestionException("Failed to parse Docling JSON response", e);
        }
        return documents;
    }

    private void extractTextRecursive(JsonNode node, StringBuilder sb) {
        if (node.isObject()) {
            if (node.has("text") && node.get("text").isTextual()) {
                sb.append(node.get("text").asText()).append("\n");
            }
            node.elements().forEachRemaining(child -> extractTextRecursive(child, sb));
        } else if (node.isArray()) {
            node.elements().forEachRemaining(child -> extractTextRecursive(child, sb));
        }
    }
}
