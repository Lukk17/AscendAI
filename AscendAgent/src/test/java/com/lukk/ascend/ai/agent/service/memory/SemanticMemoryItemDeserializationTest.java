package com.lukk.ascend.ai.agent.service.memory;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SemanticMemoryItemDeserializationTest {

    private final ObjectMapper objectMapper = new ObjectMapper().registerModule(new JavaTimeModule());

    @Test
    void deserialize_FromMem0SnakeCaseFields_ThenAllFieldsPopulated() throws Exception {
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

        SemanticMemoryItem item = objectMapper.readValue(json, SemanticMemoryItem.class);

        assertThat(item.id()).isEqualTo("abc");
        assertThat(item.userId()).isEqualTo("frosty");
        assertThat(item.text()).isEqualTo("User's name is Luke");
        assertThat(item.score()).isEqualTo(0.91);
        assertThat(item.createdAt()).isNotNull();
        assertThat(item.metadata()).isEmpty();
    }

    @Test
    void deserialize_FromCamelCaseFields_ThenStillWorks() throws Exception {
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

        SemanticMemoryItem item = objectMapper.readValue(json, SemanticMemoryItem.class);

        assertThat(item.userId()).isEqualTo("frosty");
        assertThat(item.text()).isEqualTo("User's name is Luke");
        assertThat(item.createdAt()).isNotNull();
    }
}
