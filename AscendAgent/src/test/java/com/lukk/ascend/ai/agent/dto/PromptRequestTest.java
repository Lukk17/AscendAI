package com.lukk.ascend.ai.agent.dto;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class PromptRequestTest {

    @Test
    @DisplayName("accessors return values set via canonical constructor")
    void accessors_ReturnConstructedValues() {
        // given
        PromptRequest req = new PromptRequest("hello", "http://img", "http://doc");

        // then
        assertThat(req.prompt()).isEqualTo("hello");
        assertThat(req.imageUrl()).isEqualTo("http://img");
        assertThat(req.documentUrl()).isEqualTo("http://doc");
    }

    @Test
    @DisplayName("equals and hashCode are symmetric when all fields match")
    void equalsAndHashCode_AreSymmetricForSameFields() {
        // given
        PromptRequest a = new PromptRequest("p", "i", "d");
        PromptRequest b = new PromptRequest("p", "i", "d");

        // then
        assertThat(a)
                .isEqualTo(b)
                .hasSameHashCodeAs(b)
                .isNotEqualTo(null);
        assertThat(b).isEqualTo(a);
    }

    @Test
    @DisplayName("equals returns false when compared with an unrelated type")
    void equals_ReturnsFalseAgainstUnrelatedType() {
        // given
        PromptRequest req = new PromptRequest("p", "i", "d");
        Object unrelated = "not-a-request";

        // then
        assertThat(req.equals(unrelated)).isFalse();
    }

    @Test
    @DisplayName("not equal when any single field differs")
    void notEqual_WhenAnyFieldDiffers() {
        // given
        PromptRequest base = new PromptRequest("p", "i", "d");

        // then
        assertThat(base).isNotEqualTo(new PromptRequest("X", "i", "d"));
        assertThat(base).isNotEqualTo(new PromptRequest("p", "X", "d"));
        assertThat(base).isNotEqualTo(new PromptRequest("p", "i", "X"));
    }

    @Test
    @DisplayName("toString contains all non-null field values")
    void toString_ContainsFieldValues() {
        // given
        PromptRequest req = new PromptRequest("hi", null, null);

        // then
        assertThat(req.toString()).contains("hi");
    }
}
