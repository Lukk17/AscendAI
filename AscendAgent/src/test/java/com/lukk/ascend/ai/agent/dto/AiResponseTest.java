package com.lukk.ascend.ai.agent.dto;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AiResponseTest {

    @Test
    void accessors_ReturnConstructedValues() {
        AiResponse r = new AiResponse("answer", null);

        assertThat(r.content()).isEqualTo("answer");
        assertThat(r.metadata()).isNull();
    }

    @Test
    void equalsAndHashCode_AreSymmetric() {
        AiResponse a = new AiResponse("x", null);
        AiResponse b = new AiResponse("x", null);

        assertThat(a).isEqualTo(b);
        assertThat(b).isEqualTo(a);
        assertThat(a.hashCode()).isEqualTo(b.hashCode());
        assertThat(a).isNotEqualTo(new AiResponse("y", null));
        assertThat(a).isNotEqualTo(null);
    }
}
