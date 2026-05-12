package com.lukk.ascend.ai.agent.dto;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class PromptRequestTest {

    @Test
    void accessors_ReturnConstructedValues() {
        PromptRequest req = new PromptRequest("hello", "http://img", "http://doc");

        assertThat(req.prompt()).isEqualTo("hello");
        assertThat(req.imageUrl()).isEqualTo("http://img");
        assertThat(req.documentUrl()).isEqualTo("http://doc");
    }

    @Test
    void equalsAndHashCode_AreSymmetricForSameFields() {
        PromptRequest a = new PromptRequest("p", "i", "d");
        PromptRequest b = new PromptRequest("p", "i", "d");

        assertThat(a).isEqualTo(b);
        assertThat(b).isEqualTo(a);
        assertThat(a.hashCode()).isEqualTo(b.hashCode());
        assertThat(a).isEqualTo(a);
        assertThat(a).isNotEqualTo(null);
        assertThat(a).isNotEqualTo("not-a-request");
    }

    @Test
    void notEqual_WhenAnyFieldDiffers() {
        PromptRequest base = new PromptRequest("p", "i", "d");

        assertThat(base).isNotEqualTo(new PromptRequest("X", "i", "d"));
        assertThat(base).isNotEqualTo(new PromptRequest("p", "X", "d"));
        assertThat(base).isNotEqualTo(new PromptRequest("p", "i", "X"));
    }

    @Test
    void toString_ContainsFieldValues() {
        PromptRequest req = new PromptRequest("hi", null, null);

        assertThat(req.toString()).contains("hi");
    }
}
