package com.lukk.ascend.ai.agent.dto;

import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class CustomMetadataTest {

    @Test
    void accessors_ReturnConstructedValues() {
        ChatResponseMetadata delegate = ChatResponseMetadata.builder().model("m1").build();
        List<String> tools = List.of("tool-a", "tool-b");

        CustomMetadata meta = new CustomMetadata(delegate, tools);

        assertThat(meta.getDelegate()).isSameAs(delegate);
        assertThat(meta.getToolsUsed()).containsExactly("tool-a", "tool-b");
    }

    @Test
    void equalsAndHashCode_AreReflexiveAndDifferentiateOnToolsField() {
        ChatResponseMetadata delegate = ChatResponseMetadata.builder().model("m1").build();
        CustomMetadata a = new CustomMetadata(delegate, List.of("x"));
        CustomMetadata different = new CustomMetadata(delegate, List.of("y"));

        // reflexive
        assertThat(a).isEqualTo(a);
        assertThat(a.hashCode()).isEqualTo(a.hashCode());
        // toolsUsed differs → not equal (callSuper=true means same delegate ref helps,
        // but Lombok's generated equals also compare the toolsUsed list)
        assertThat(a).isNotEqualTo(different);
        // null + foreign type
        assertThat(a).isNotEqualTo(null);
        assertThat(a).isNotEqualTo("not-a-metadata");
    }
}
