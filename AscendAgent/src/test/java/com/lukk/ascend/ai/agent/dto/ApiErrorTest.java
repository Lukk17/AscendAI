package com.lukk.ascend.ai.agent.dto;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ApiErrorTest {

    @Test
    void accessors_ReturnConstructedValues() {
        ApiError e = new ApiError(400, "bad", "boom");

        assertThat(e.status()).isEqualTo(400);
        assertThat(e.error()).isEqualTo("bad");
        assertThat(e.message()).isEqualTo("boom");
    }

    @Test
    void equalsAndHashCode_AreSymmetric() {
        ApiError a = new ApiError(400, "bad", "boom");
        ApiError b = new ApiError(400, "bad", "boom");

        assertThat(a).isEqualTo(b);
        assertThat(b).isEqualTo(a);
        assertThat(a.hashCode()).isEqualTo(b.hashCode());
        assertThat(a).isNotEqualTo(new ApiError(401, "bad", "boom"));
        assertThat(a).isNotEqualTo(new ApiError(400, "BAD", "boom"));
        assertThat(a).isNotEqualTo(new ApiError(400, "bad", "OTHER"));
        assertThat(a).isNotEqualTo(null);
        assertThat(a).isNotEqualTo("string");
    }

    @Test
    void toString_ContainsValues() {
        ApiError e = new ApiError(500, "ise", "kaboom");

        assertThat(e.toString()).contains("500", "ise", "kaboom");
    }
}
