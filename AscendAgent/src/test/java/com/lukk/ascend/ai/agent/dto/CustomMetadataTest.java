package com.lukk.ascend.ai.agent.dto;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class CustomMetadataTest {

    @Test
    @DisplayName("accessor methods return the values passed to the canonical constructor")
    void accessors_ReturnConstructedValues() {
        // given
        ChatResponseMetadata delegate = ChatResponseMetadata.builder().model("m1").build();
        List<String> tools = List.of("tool-a", "tool-b");

        // when
        CustomMetadata meta = new CustomMetadata(delegate, tools);

        // then
        assertThat(meta.delegate()).isSameAs(delegate);
        assertThat(meta.toolsUsed()).containsExactly("tool-a", "tool-b");
    }

    @Test
    @DisplayName("equals is reflexive, value-equal on same components, and differentiates on toolsUsed")
    void equalsAndHashCode_AreReflexiveAndDifferentiateOnToolsField() {
        // given
        ChatResponseMetadata delegate = ChatResponseMetadata.builder().model("m1").build();
        CustomMetadata original = new CustomMetadata(delegate, List.of("x"));
        CustomMetadata sameComponents = new CustomMetadata(delegate, List.of("x"));
        CustomMetadata differentTools = new CustomMetadata(delegate, List.of("y"));

        // then
        assertThat(original)
                .isEqualTo(sameComponents)
                .hasSameHashCodeAs(sameComponents)
                .isNotEqualTo(differentTools)
                .isNotEqualTo(null);
    }

    @Test
    @DisplayName("equals returns false when compared with an unrelated type")
    void equals_ReturnsFalseAgainstUnrelatedType() {
        // given
        CustomMetadata meta = new CustomMetadata(null, List.of());
        Object unrelated = new Object();

        // then
        assertThat(meta.equals(unrelated)).isFalse();
    }
}
