package com.lukk.ascend.ai.agent.service.memory;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class SemanticMemoryExtractorMetricsTest {

    private static final String PROVIDER = "openai";
    private static final String MODEL = "gpt-4o-mini";

    private MeterRegistry registry;
    private SemanticMemoryExtractor extractor;

    @BeforeEach
    void setUp() {
        // given
        registry = new SimpleMeterRegistry();
        extractor = new SemanticMemoryExtractor(null, null, null, new ObjectMapper(), null, null, registry);
    }

    @Test
    @DisplayName("extractFactsFromJson increments memory.extraction.parse_failed once for prose with no JSON array")
    void extractFactsFromJson_WhenProseWithNoJsonArray_ThenIncrementsParseFailedCounterOnce() {
        // given
        String prose = "I thought about this for a while and found no facts worth saving at all";

        // when
        List<String> facts = extractor.extractFactsFromJson(prose, PROVIDER, MODEL);

        // then
        assertThat(facts).isEmpty();
        Counter counter = registry.find("memory.extraction.parse_failed")
                .tag("provider", PROVIDER)
                .tag("model", MODEL)
                .counter();
        assertThat(counter).isNotNull();
        assertThat(counter.count()).isEqualTo(1.0);
    }

    @Test
    @DisplayName("extractFactsFromJson leaves memory.extraction.parse_failed at zero for a valid JSON array")
    void extractFactsFromJson_WhenValidJsonArray_ThenParseFailedCounterStaysZero() {
        // given
        String valid = "[\"User likes tea\"]";

        // when
        List<String> facts = extractor.extractFactsFromJson(valid, PROVIDER, MODEL);

        // then
        assertThat(facts).containsExactly("User likes tea");
        Counter counter = registry.find("memory.extraction.parse_failed")
                .tag("provider", PROVIDER)
                .tag("model", MODEL)
                .counter();
        double count = counter == null ? 0.0 : counter.count();
        assertThat(count).isEqualTo(0.0);
    }
}
