package com.lukk.ascend.ai.agent.service.memory;

import com.lukk.ascend.ai.agent.config.properties.SemanticMemoryProperties;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.web.client.RestClient;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Extra branch coverage for SemanticMemoryClient:
 *  - Blank userId short-circuits all operations
 *  - insertMemory when disabled
 *  - wipeUserMemory when disabled
 *  - deleteMemory when memoryId is blank
 *  - deleteMemory when disabled
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class SemanticMemoryClientExtraCoverageTest {

    @Mock
    private RestClient.Builder restClientBuilder;

    private SemanticMemoryProperties properties;
    private SemanticMemoryClient client;

    @BeforeEach
    void setUp() {
        properties = new SemanticMemoryProperties();
        properties.setEnabled(true);
        properties.setBaseUrl("http://localhost:7020");
        client = new SemanticMemoryClient(restClientBuilder, properties);
    }

    // ------------------------------------------------------------------ blank userId short-circuits

    @Test
    @DisplayName("search returns empty list when userId is blank")
    void search_BlankUserId_ReturnsEmptyList() {
        List<SemanticMemoryItem> result = client.search("", "query", 5, "lmstudio");
        assertThat(result).isEmpty();
    }

    @Test
    @DisplayName("search returns empty list when userId is null")
    void search_NullUserId_ReturnsEmptyList() {
        List<SemanticMemoryItem> result = client.search(null, "query", 5, "lmstudio");
        assertThat(result).isEmpty();
    }

    @Test
    @DisplayName("insertMemory does nothing when userId is blank")
    void insertMemory_BlankUserId_DoesNothing() {
        // must not throw or interact with rest client
        client.insertMemory("", "some fact", "lmstudio");
    }

    @Test
    @DisplayName("wipeUserMemory does nothing when userId is blank")
    void wipeUserMemory_BlankUserId_DoesNothing() {
        client.wipeUserMemory("", "lmstudio");
    }

    @Test
    @DisplayName("deleteMemory does nothing when userId is blank")
    void deleteMemory_BlankUserId_DoesNothing() {
        client.deleteMemory("", "mem-123", "lmstudio");
    }

    // ------------------------------------------------------------------ disabled state

    @Test
    @DisplayName("search returns empty list when semantic memory is disabled")
    void search_Disabled_ReturnsEmptyList() {
        properties.setEnabled(false);
        List<SemanticMemoryItem> result = client.search("frosty", "query", 5, "lmstudio");
        assertThat(result).isEmpty();
    }

    @Test
    @DisplayName("insertMemory does nothing when semantic memory is disabled")
    void insertMemory_Disabled_DoesNothing() {
        properties.setEnabled(false);
        client.insertMemory("frosty", "some fact", "lmstudio");
        // no interaction with restClientBuilder
    }

    @Test
    @DisplayName("wipeUserMemory does nothing when semantic memory is disabled")
    void wipeUserMemory_Disabled_DoesNothing() {
        properties.setEnabled(false);
        client.wipeUserMemory("frosty", "lmstudio");
    }

    @Test
    @DisplayName("deleteMemory does nothing when semantic memory is disabled")
    void deleteMemory_Disabled_DoesNothing() {
        properties.setEnabled(false);
        client.deleteMemory("frosty", "mem-123", "lmstudio");
    }

    // ------------------------------------------------------------------ blank memoryId

    @Test
    @DisplayName("deleteMemory does nothing when memoryId is blank")
    void deleteMemory_BlankMemoryId_DoesNothing() {
        client.deleteMemory("frosty", "   ", "lmstudio");
    }

    @Test
    @DisplayName("deleteMemory does nothing when memoryId is null")
    void deleteMemory_NullMemoryId_DoesNothing() {
        client.deleteMemory("frosty", null, "lmstudio");
    }
}
