package com.lukk.ascend.ai.agent.service.ingestion.client;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.exception.IngestionException;
import com.lukk.ascend.ai.agent.service.ingestion.IngestionMetadataKeys;
import com.lukk.ascend.ai.agent.util.NamedByteArrayResource;
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
import org.springframework.web.util.UriComponentsBuilder;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@Slf4j
@Component
public class AscendOcrClient {

    private static final String TYPE_ASCEND_OCR = "ascendocr";
    private static final String PARAM_FILE = "file";
    private static final String PARAM_LANG = "lang";
    private static final String JSON_PAGES = "pages";
    private static final String JSON_LINES = "lines";
    private static final String JSON_TEXT = "text";

    private final RestClient restClient;
    private final ObjectMapper objectMapper;
    private final String ascendOcrBaseUrl;
    private final String ascendOcrApiPath;

    public AscendOcrClient(
            @Qualifier("ingestionRestClient") RestClient restClient,
            ObjectMapper objectMapper,
            @Value("${app.ascend-ocr.base-url:http://localhost:7022}") String ascendOcrBaseUrl,
            @Value("${app.ascend-ocr.api-path:/v1/ocr}") String ascendOcrApiPath) {
        this.restClient = restClient;
        this.objectMapper = objectMapper;
        this.ascendOcrBaseUrl = ascendOcrBaseUrl;
        this.ascendOcrApiPath = ascendOcrApiPath;
    }

    public List<Document> process(byte[] fileBytes, String filename, String lang) {
        log.info("[AscendOcrClient] Sending file to ascend-ocr: {}", filename);

        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add(PARAM_FILE, new NamedByteArrayResource(fileBytes, filename));

        // ascend-ocr declares `lang` as a query parameter on POST /v1/ocr, not a multipart
        // form field (see AscendAgent/src/test/resources/ascend-ocr/openapi-contract.json).
        String uri = UriComponentsBuilder.fromUriString(ascendOcrBaseUrl + ascendOcrApiPath)
                .queryParamIfPresent(PARAM_LANG, Optional.ofNullable(lang).filter(StringUtils::hasText))
                .toUriString();

        try {
            String response = restClient.post()
                    .uri(uri)
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(body)
                    .retrieve()
                    .body(String.class);
            return parseResponse(response, filename);
        } catch (RestClientException e) {
            throw new IngestionException("Failed to process document with ascend-ocr: " + filename, e);
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
                        IngestionMetadataKeys.SOURCE, filename,
                        IngestionMetadataKeys.TYPE, TYPE_ASCEND_OCR)));
            }
        } catch (JsonProcessingException e) {
            throw new IngestionException("Failed to parse ascend-ocr JSON response", e);
        }
        return documents;
    }

    private void extractPagesText(JsonNode rootNode, StringBuilder fullText) {
        if (!rootNode.has(JSON_PAGES) || !rootNode.get(JSON_PAGES).isArray()) {
            return;
        }

        for (JsonNode pageNode : rootNode.get(JSON_PAGES)) {
            extractLinesText(pageNode, fullText);
        }
    }

    private void extractLinesText(JsonNode pageNode, StringBuilder fullText) {
        if (!pageNode.has(JSON_LINES) || !pageNode.get(JSON_LINES).isArray()) {
            return;
        }

        for (JsonNode lineNode : pageNode.get(JSON_LINES)) {
            if (lineNode.has(JSON_TEXT)) {
                fullText.append(lineNode.get(JSON_TEXT).asText()).append("\n");
            }
        }
    }
}
