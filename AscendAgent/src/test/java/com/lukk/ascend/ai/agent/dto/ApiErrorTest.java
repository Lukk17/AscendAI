package com.lukk.ascend.ai.agent.dto;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ApiErrorTest {

    @Test
    @DisplayName("accessors return values set via constructor")
    void accessors_ReturnConstructedValues() {
        // given
        ApiError e = new ApiError(400, "bad", "boom");

        // then
        assertThat(e.status()).isEqualTo(400);
        assertThat(e.error()).isEqualTo("bad");
        assertThat(e.message()).isEqualTo("boom");
    }

    @Test
    @DisplayName("equals and hashCode are symmetric for equal records")
    void equalsAndHashCode_AreSymmetric() {
        // given
        ApiError a = new ApiError(400, "bad", "boom");
        ApiError b = new ApiError(400, "bad", "boom");

        // then
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
    @DisplayName("toString contains all field values")
    void toString_ContainsValues() {
        // given
        ApiError e = new ApiError(500, "ise", "kaboom");

        // then
        assertThat(e.toString()).contains("500", "ise", "kaboom");
    }
}
