package com.lukk.ascend.ai.agent.dto;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AiResponseTest {

    @DisplayName("accessors return constructed values")
    @Test
    void accessors_ReturnConstructedValues() {
        // given
        AiResponse r = new AiResponse("answer", null);

        // then
        assertThat(r.content()).isEqualTo("answer");
        assertThat(r.metadata()).isNull();
    }

    @DisplayName("equals and hash code are symmetric")
    @Test
    void equalsAndHashCode_AreSymmetric() {
        // given
        AiResponse a = new AiResponse("x", null);
        AiResponse b = new AiResponse("x", null);

        // then
        assertThat(a).isEqualTo(b);
        assertThat(b).isEqualTo(a);
        assertThat(a.hashCode()).isEqualTo(b.hashCode());
        assertThat(a).isNotEqualTo(new AiResponse("y", null));
        assertThat(a).isNotEqualTo(null);
    }
}
