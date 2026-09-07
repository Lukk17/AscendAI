package com.lukk.ascend.ai.agent.dto;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class UploadResponseTest {

    @DisplayName("accessors return constructed values")
    @Test
    void accessors_ReturnConstructedValues() {
        // given
        UploadResponse r = new UploadResponse(List.of("a"), List.of("b"));

        // then
        assertThat(r.uploaded()).containsExactly("a");
        assertThat(r.failures()).containsExactly("b");
    }

    @DisplayName("equals and hash code are symmetric")
    @Test
    void equalsAndHashCode_AreSymmetric() {
        // given
        UploadResponse a = new UploadResponse(List.of("a"), List.of());
        UploadResponse b = new UploadResponse(List.of("a"), List.of());

        // then
        assertThat(a).isEqualTo(b);
        assertThat(b).isEqualTo(a);
        assertThat(a.hashCode()).isEqualTo(b.hashCode());
        assertThat(a).isNotEqualTo(new UploadResponse(List.of(), List.of()));
        assertThat(a).isNotEqualTo(null);
    }
}
