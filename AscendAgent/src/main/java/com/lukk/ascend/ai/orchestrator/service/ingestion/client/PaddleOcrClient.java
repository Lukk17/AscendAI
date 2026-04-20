package com.lukk.ascend.ai.orchestrator.service.ingestion.client;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.orchestrator.exception.IngestionException;
import com.lukk.ascend.ai.orchestrator.util.NamedByteArrayResource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.document.Document;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@Slf4j
@Component
public class PaddleOcrClient {

    private static final String TYPE_PADDLE_OCR = "paddleocr";
    private static final String KEY_SOURCE = "source";
    private static final String KEY_TYPE = "type";
    private static final String PARAM_FILES = "files";
    private static final String PARAM_LANG = "lang";

    private final RestClient restClient;
    private final ObjectMapper objectMapper;
    private final String paddleBaseUrl;
    private final String paddleApiPath;

    public PaddleOcrClient(
            @Qualifier("ingestionRestClient") RestClient restClient,
            ObjectMapper objectMapper,
            @Value("${app.paddleocr.base-url:http://localhost:7022}") String paddleBaseUrl,
            @Value("${app.paddleocr.api-path:/v1/ocr}") String paddleApiPath) {
        this.restClient = restClient;
        this.objectMapper = objectMapper;
        this.paddleBaseUrl = paddleBaseUrl;
        this.paddleApiPath = paddleApiPath;
    }

    public List<Document> process(byte[] fileBytes, String filename, String lang) {
        log.info("[PaddleOcrClient] Sending file to PaddleOCR: {}", filename);

        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add(PARAM_FILES, new NamedByteArrayResource(fileBytes, filename));
        Optional.ofNullable(lang)
                .filter(StringUtils::hasText)
                .ifPresent(l -> body.add(PARAM_LANG, l));

        try {
            String response = restClient.post()
                    .uri(paddleBaseUrl + paddleApiPath)
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(body)
                    .retrieve()
                    .body(String.class);
            return parseResponse(response, filename);
        } catch (RestClientException e) {
            throw new IngestionException("Failed to process document with PaddleOCR: " + filename, e);
        }
    }

    private List<Document> parseResponse(String jsonResponse, String filename) {
        List<Document> documents = new ArrayList<>();
        try {
            JsonNode rootNode = objectMapper.readTree(jsonResponse);
            StringBuilder fullText = new StringBuilder();

            extractPagesText(rootNode, fullText);

            if (!fullText.isEmpty()) {
                documents.add(new Document(fullText.toString(), Map.of(
                        KEY_SOURCE, filename,
                        KEY_TYPE, TYPE_PADDLE_OCR)));
            }
        } catch (JsonProcessingException e) {
            throw new IngestionException("Failed to parse PaddleOCR JSON response", e);
        }
        return documents;
    }

    private void extractPagesText(JsonNode rootNode, StringBuilder fullText) {
        if (!rootNode.has("pages") || !rootNode.get("pages").isArray()) {
            return;
        }
        for (JsonNode pageNode : rootNode.get("pages")) {
            extractLinesText(pageNode, fullText);
        }
    }

    private void extractLinesText(JsonNode pageNode, StringBuilder fullText) {
        if (!pageNode.has("lines") || !pageNode.get("lines").isArray()) {
            return;
        }
        for (JsonNode lineNode : pageNode.get("lines")) {
            if (lineNode.has("text")) {
                fullText.append(lineNode.get("text").asText()).append("\n");
            }
        }
    }
}
