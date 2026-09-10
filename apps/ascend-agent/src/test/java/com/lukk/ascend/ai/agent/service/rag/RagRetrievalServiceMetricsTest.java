package com.lukk.ascend.ai.agent.service.rag;

import com.lukk.ascend.ai.agent.config.properties.RagProperties;
import com.lukk.ascend.ai.agent.service.provider.VectorStoreResolver;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class RagRetrievalServiceMetricsTest {

    private static final String PROVIDER = "openai";
    private static final String BUCKET = "knowledge-base";

    @Mock
    private VectorStoreResolver vectorStoreResolver;

    @Mock
    private RagProperties ragProperties;

    @Mock
    private VectorStore vectorStore;

    private MeterRegistry registry;
    private RagRetrievalService service;

    @BeforeEach
    void setUp() {
        registry = new SimpleMeterRegistry();
        service = new RagRetrievalService(vectorStoreResolver, ragProperties, BUCKET, registry);

        lenient().when(ragProperties.isEnabled()).thenReturn(true);
        lenient().when(ragProperties.getTopK()).thenReturn(5);
        lenient().when(ragProperties.getSimilarityThreshold()).thenReturn(0.5);
        lenient().when(ragProperties.getMaxContextChars()).thenReturn(4000);
        lenient().when(vectorStoreResolver.resolve(PROVIDER)).thenReturn(vectorStore);
        lenient().when(vectorStoreResolver.resolveProviderName(any())).thenReturn("ascendai-1536");
    }

    @Test
    @DisplayName("rag.last_top_score gauge is registered by the constructor")
    void constructor_RegistersLastTopScoreGauge() {
        // then
        Gauge gauge = registry.find("rag.last_top_score").gauge();
        assertThat(gauge).isNotNull();
    }

    @Test
    @DisplayName("retrieve registers rag.retrieval.duration timer with provider and outcome=ok tags on success")
    void retrieve_Success_RegistersRetrievalDurationTimer() {
        // given
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of());

        // when
        service.retrieve("test query", PROVIDER);

        // then
        Timer timer = registry.find("rag.retrieval.duration")
                .tag("provider", PROVIDER)
                .tag("outcome", "ok")
                .timer();
        assertThat(timer).isNotNull();
        assertThat(timer.count()).isEqualTo(1);
    }

    @Test
    @DisplayName("retrieve registers rag.retrieval.hits counter with above_threshold=true for docs above threshold")
    void retrieve_DocAboveThreshold_RegistersHitCounterTrue() {
        // given
        Document doc = mockDoc("content", 0.9, Map.of("source", "doc.pdf"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        // when
        service.retrieve("test query", PROVIDER);

        // then
        Counter counter = registry.find("rag.retrieval.hits")
                .tag("provider", PROVIDER)
                .tag("above_threshold", "true")
                .counter();
        assertThat(counter).isNotNull();
        assertThat(counter.count()).isEqualTo(1.0);
    }

    @Test
    @DisplayName("retrieve registers rag.retrieval.hits counter with above_threshold=false for docs below threshold")
    void retrieve_DocBelowThreshold_RegistersHitCounterFalse() {
        // given — score 0.3 < threshold 0.5
        Document doc = mockDoc("content", 0.3, Map.of("source", "doc.pdf"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        // when
        service.retrieve("test query", PROVIDER);

        // then
        Counter counter = registry.find("rag.retrieval.hits")
                .tag("provider", PROVIDER)
                .tag("above_threshold", "false")
                .counter();
        assertThat(counter).isNotNull();
        assertThat(counter.count()).isEqualTo(1.0);
    }

    @Test
    @DisplayName("retrieve updates rag.last_top_score gauge to the max score among candidates")
    void retrieve_WithCandidates_UpdatesLastTopScoreGauge() {
        // given
        Document d1 = mockDoc("a", 0.75, Map.of("source", "a.pdf"));
        Document d2 = mockDoc("b", 0.92, Map.of("source", "b.pdf"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(d1, d2));

        // when
        service.retrieve("test query", PROVIDER);

        // then
        Gauge gauge = registry.find("rag.last_top_score").gauge();
        assertThat(gauge).isNotNull();
        assertThat(gauge.value()).isEqualTo(0.92);
    }

    private Document mockDoc(String text, double score, Map<String, Object> metadata) {
        Document doc = mock(Document.class);
        lenient().when(doc.getText()).thenReturn(text);
        lenient().when(doc.getScore()).thenReturn(score);
        lenient().when(doc.getMetadata()).thenReturn(metadata);
        return doc;
    }
}
