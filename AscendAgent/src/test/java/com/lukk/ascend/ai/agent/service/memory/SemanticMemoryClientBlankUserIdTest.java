package com.lukk.ascend.ai.agent.service.memory;

import com.lukk.ascend.ai.agent.config.properties.SemanticMemoryProperties;
import com.lukk.ascend.ai.agent.test.TestConstants;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class SemanticMemoryClientBlankUserIdTest {

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


    @Test
    @DisplayName("search returns empty list when userId is blank")
    void search_BlankUserId_ReturnsEmptyList() {
        // then
        assertThat(client.search("", "query", 5, "lmstudio")).isEmpty();
    }

    @Test
    @DisplayName("search returns empty list when userId is null")
    void search_NullUserId_ReturnsEmptyList() {
        // then
        assertThat(client.search(null, "query", 5, "lmstudio")).isEmpty();
    }

    @Test
    @DisplayName("insertMemory does nothing when userId is blank")
    void insertMemory_BlankUserId_DoesNothing() {
        // then
        client.insertMemory("", "some fact", "lmstudio");
    }

    @Test
    @DisplayName("wipeUserMemory does nothing when userId is blank")
    void wipeUserMemory_BlankUserId_DoesNothing() {
        // then
        client.wipeUserMemory("", "lmstudio");
    }

    @Test
    @DisplayName("deleteMemory does nothing when userId is blank")
    void deleteMemory_BlankUserId_DoesNothing() {
        // then
        client.deleteMemory("", "mem-123", "lmstudio");
    }


    @Test
    @DisplayName("search returns empty list when semantic memory is disabled")
    void search_Disabled_ReturnsEmptyList() {
        // given
        properties.setEnabled(false);

        // then
        assertThat(client.search(TestConstants.DEFAULT_USER_ID, "query", 5, "lmstudio")).isEmpty();
    }

    @Test
    @DisplayName("insertMemory does nothing when semantic memory is disabled")
    void insertMemory_Disabled_DoesNothing() {
        // given
        properties.setEnabled(false);

        // then
        client.insertMemory(TestConstants.DEFAULT_USER_ID, "some fact", "lmstudio");
    }

    @Test
    @DisplayName("wipeUserMemory does nothing when semantic memory is disabled")
    void wipeUserMemory_Disabled_DoesNothing() {
        // given
        properties.setEnabled(false);

        // then
        client.wipeUserMemory(TestConstants.DEFAULT_USER_ID, "lmstudio");
    }

    @Test
    @DisplayName("deleteMemory does nothing when semantic memory is disabled")
    void deleteMemory_Disabled_DoesNothing() {
        // given
        properties.setEnabled(false);

        // then
        client.deleteMemory(TestConstants.DEFAULT_USER_ID, "mem-123", "lmstudio");
    }


    @Test
    @DisplayName("deleteMemory does nothing when memoryId is blank")
    void deleteMemory_BlankMemoryId_DoesNothing() {
        // then
        client.deleteMemory(TestConstants.DEFAULT_USER_ID, "   ", "lmstudio");
    }

    @Test
    @DisplayName("deleteMemory does nothing when memoryId is null")
    void deleteMemory_NullMemoryId_DoesNothing() {
        // then
        client.deleteMemory(TestConstants.DEFAULT_USER_ID, null, "lmstudio");
    }
}
