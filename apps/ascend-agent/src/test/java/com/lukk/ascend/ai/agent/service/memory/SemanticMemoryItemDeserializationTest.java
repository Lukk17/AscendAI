package com.lukk.ascend.ai.agent.service.memory;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SemanticMemoryItemDeserializationTest {

    private final ObjectMapper objectMapper = new ObjectMapper().registerModule(new JavaTimeModule());

    @DisplayName("deserialize from mem0 snake case fields then all fields populated")
    @Test
    void deserialize_FromMem0SnakeCaseFields_ThenAllFieldsPopulated() throws Exception {
        // given
        String json = """
                {
                  "id": "abc",
                  "user_id": "frosty",
                  "memory": "User's name is Luke",
                  "score": 0.91,
                  "created_at": "2026-05-08T09:15:41Z",
                  "metadata": {}
                }
                """;

        // when
        SemanticMemoryItem item = objectMapper.readValue(json, SemanticMemoryItem.class);

        // then
        assertThat(item.id()).isEqualTo("abc");
        assertThat(item.userId()).isEqualTo("frosty");
        assertThat(item.text()).isEqualTo("User's name is Luke");
        assertThat(item.score()).isEqualTo(0.91);
        assertThat(item.createdAt()).isNotNull();
        assertThat(item.metadata()).isEmpty();
    }

    @DisplayName("deserialize from camel case fields then still works")
    @Test
    void deserialize_FromCamelCaseFields_ThenStillWorks() throws Exception {
        // given
        String json = """
                {
                  "id": "abc",
                  "userId": "frosty",
                  "text": "User's name is Luke",
                  "score": 0.91,
                  "createdAt": "2026-05-08T09:15:41Z",
                  "metadata": {}
                }
                """;

        // when
        SemanticMemoryItem item = objectMapper.readValue(json, SemanticMemoryItem.class);

        // then
        assertThat(item.userId()).isEqualTo("frosty");
        assertThat(item.text()).isEqualTo("User's name is Luke");
        assertThat(item.createdAt()).isNotNull();
    }
}
