package com.lukk.ascend.ai.agent.service.memory;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties.ProviderConfig;
import com.lukk.ascend.ai.agent.service.ChatModelResolver;
import com.lukk.ascend.ai.agent.service.ChatResponseContentResolver;
import com.lukk.ascend.ai.agent.service.cache.NoopPromptCacheStrategy;
import com.lukk.ascend.ai.agent.service.cache.PromptCacheStrategy;
import com.lukk.ascend.ai.agent.service.cache.PromptCacheStrategyResolver;
import com.lukk.ascend.ai.agent.test.TestConstants;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.ai.chat.prompt.Prompt;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.after;
import static org.mockito.Mockito.doNothing;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class SemanticMemoryExtractorTest {

    private static final String DEFAULT_USER_ID = TestConstants.DEFAULT_USER_ID;
    private static final String DEFAULT_USER_TEXT = "My dog is named Rex";
    private static final String DEFAULT_PROVIDER = "lmstudio";
    private static final String DEFAULT_EMBEDDING_PROVIDER = "lmstudio";

    @Mock
    private ChatModelResolver chatModelResolver;

    @Mock
    private AiProviderProperties aiProviderProperties;

    @Mock
    private SemanticMemoryClient memoryClient;

    @Mock
    private ObjectMapper objectMapper;

    @Mock
    private ChatResponseContentResolver chatResponseContentResolver;

    @Mock
    private ChatModel chatModel;

    @Mock
    private PromptCacheStrategyResolver cacheStrategyResolver;

    @InjectMocks
    private SemanticMemoryExtractor extractor;

    @org.junit.jupiter.api.BeforeEach
    void setupCacheResolver() {
        PromptCacheStrategy noop = new NoopPromptCacheStrategy(DEFAULT_PROVIDER);
        org.mockito.Mockito.lenient().when(cacheStrategyResolver.resolve(any())).thenReturn(noop);
    }

    @Test
    @DisplayName("extract saves valid facts to memory asynchronously")
    void extract_WhenValidFactsReturned_ThenSavesMemoryAsynchronously() throws JsonProcessingException {
        // given
        setupProviderConfig("meta-llama-3.1-8b-instruct");
        when(chatModelResolver.resolve(DEFAULT_PROVIDER)).thenReturn(chatModel);

        String jsonResponse = "[\"User has a dog named Rex\"]";
        ChatResponse mockResponse = createMockChatResponse(jsonResponse);
        when(chatModel.call(any(Prompt.class))).thenReturn(mockResponse);
        when(chatResponseContentResolver.resolveContent(mockResponse)).thenReturn(jsonResponse);

        List<String> parsedFacts = List.of("User has a dog named Rex");
        when(objectMapper.readValue(eq(jsonResponse), org.mockito.ArgumentMatchers.<TypeReference<List<String>>>any())).thenReturn(parsedFacts);

        // when
        extractor.extract(DEFAULT_USER_ID, DEFAULT_USER_TEXT, DEFAULT_PROVIDER, null, DEFAULT_EMBEDDING_PROVIDER);

        // then
        verify(memoryClient, timeout(2000)).insertMemory(DEFAULT_USER_ID, "User has a dog named Rex", DEFAULT_EMBEDDING_PROVIDER);
    }

    @Test
    @DisplayName("extract does not call insertMemory when the extracted facts list is empty")
    void extract_WhenEmptyFactsReturned_ThenDoesNotSaveMemory() throws JsonProcessingException {
        // given
        setupProviderConfig("meta-llama-3.1-8b-instruct");
        when(chatModelResolver.resolve(DEFAULT_PROVIDER)).thenReturn(chatModel);

        String jsonResponse = "[]";
        ChatResponse mockResponse = createMockChatResponse(jsonResponse);
        when(chatModel.call(any(Prompt.class))).thenReturn(mockResponse);
        when(chatResponseContentResolver.resolveContent(mockResponse)).thenReturn(jsonResponse);

        List<String> parsedFacts = List.of();
        when(objectMapper.readValue(eq(jsonResponse), org.mockito.ArgumentMatchers.<TypeReference<List<String>>>any())).thenReturn(parsedFacts);

        // when
        extractor.extract(DEFAULT_USER_ID, DEFAULT_USER_TEXT, DEFAULT_PROVIDER, null, DEFAULT_EMBEDDING_PROVIDER);

        // then
        verify(chatModelResolver, timeout(2000)).resolve(DEFAULT_PROVIDER);
        verify(memoryClient, after(500).never()).insertMemory(any(), any(), any());
    }

    @Test
    @DisplayName("extract handles gracefully when the AI provider throws an exception")
    void extract_WhenAiThrowsException_ThenHandlesGracefully() {
        // given
        setupProviderConfig("meta-llama-3.1-8b-instruct");
        when(chatModelResolver.resolve(DEFAULT_PROVIDER)).thenReturn(chatModel);
        when(chatModel.call(any(Prompt.class))).thenThrow(new RuntimeException("AI Provider Down"));

        // when
        extractor.extract(DEFAULT_USER_ID, DEFAULT_USER_TEXT, DEFAULT_PROVIDER, null, DEFAULT_EMBEDDING_PROVIDER);

        // then
        verify(chatModelResolver, timeout(2000)).resolve(DEFAULT_PROVIDER);
        verify(memoryClient, after(500).never()).insertMemory(any(), any(), any());
    }

    @Test
    @DisplayName("extract handles gracefully when the JSON response cannot be parsed")
    void extract_WhenJsonProcessingException_ThenHandlesGracefully() throws JsonProcessingException {
        // given
        setupProviderConfig("meta-llama-3.1-8b-instruct");
        when(chatModelResolver.resolve(DEFAULT_PROVIDER)).thenReturn(chatModel);

        String invalidJson = "Invalid output with no JSON at all";
        ChatResponse mockResponse = createMockChatResponse(invalidJson);
        when(chatModel.call(any(Prompt.class))).thenReturn(mockResponse);
        when(chatResponseContentResolver.resolveContent(mockResponse)).thenReturn(invalidJson);

        when(objectMapper.readValue(any(String.class), org.mockito.ArgumentMatchers.<TypeReference<List<String>>>any()))
                .thenThrow(new JsonProcessingException("Malformatted JSON") {
                });

        // when
        extractor.extract(DEFAULT_USER_ID, DEFAULT_USER_TEXT, DEFAULT_PROVIDER, null, DEFAULT_EMBEDDING_PROVIDER);

        // then
        verify(chatModelResolver, timeout(2000)).resolve(DEFAULT_PROVIDER);
        verify(memoryClient, after(500).never()).insertMemory(any(), any(), any());
    }

    @Test
    @DisplayName("extract parses facts from an embedded JSON array inside thinking model reasoning text")
    void extract_WhenThinkingModelReturnsReasoningWithEmbeddedJson_ThenExtractsFactsFromEmbeddedArray() throws JsonProcessingException {
        // given — simulates the MiniMax-M2.7 bug: resolver returns thinking text with JSON embedded
        setupProviderConfig("MiniMax-M2.7");
        when(chatModelResolver.resolve(DEFAULT_PROVIDER)).thenReturn(chatModel);

        String thinkingWithEmbeddedJson = """
                The user says "My dog is named Rex." We need to identify semantic facts.
                Thus final answer: ["User has a dog named Rex"]""";
        String embeddedArray = "[\"User has a dog named Rex\"]";

        ChatResponse mockResponse = createMockChatResponse(thinkingWithEmbeddedJson);
        when(chatModel.call(any(Prompt.class))).thenReturn(mockResponse);
        when(chatResponseContentResolver.resolveContent(mockResponse)).thenReturn(thinkingWithEmbeddedJson);

        // First call with full text fails, second call with extracted array succeeds
        when(objectMapper.readValue(eq(thinkingWithEmbeddedJson), org.mockito.ArgumentMatchers.<TypeReference<List<String>>>any()))
                .thenThrow(new JsonProcessingException("Not valid JSON") {
                });
        when(objectMapper.readValue(eq(embeddedArray), org.mockito.ArgumentMatchers.<TypeReference<List<String>>>any()))
                .thenReturn(List.of("User has a dog named Rex"));

        // when
        extractor.extract(DEFAULT_USER_ID, DEFAULT_USER_TEXT, DEFAULT_PROVIDER, null, DEFAULT_EMBEDDING_PROVIDER);

        // then
        verify(memoryClient, timeout(2000)).insertMemory(DEFAULT_USER_ID, "User has a dog named Rex", DEFAULT_EMBEDDING_PROVIDER);
    }

    @Test
    @DisplayName("extract uses the last non-thinking generation when model returns multiple generations")
    void extract_WhenThinkingModelReturnsMultipleGenerations_ThenExtractsFactsFromActualContent() throws JsonProcessingException {
        // given
        setupProviderConfig("MiniMax-M2.7");
        when(chatModelResolver.resolve(DEFAULT_PROVIDER)).thenReturn(chatModel);

        String thinkingText = "Let me analyze the user input for semantic facts...";
        String jsonResponse = "[\"User has a dog named Rex\"]";
        ChatResponse mockResponse = createMockThinkingChatResponse(thinkingText, jsonResponse);
        when(chatModel.call(any(Prompt.class))).thenReturn(mockResponse);
        when(chatResponseContentResolver.resolveContent(mockResponse)).thenReturn(jsonResponse);

        List<String> parsedFacts = List.of("User has a dog named Rex");
        when(objectMapper.readValue(eq(jsonResponse), org.mockito.ArgumentMatchers.<TypeReference<List<String>>>any())).thenReturn(parsedFacts);

        // when
        extractor.extract(DEFAULT_USER_ID, DEFAULT_USER_TEXT, DEFAULT_PROVIDER, null, DEFAULT_EMBEDDING_PROVIDER);

        // then
        verify(memoryClient, timeout(2000)).insertMemory(DEFAULT_USER_ID, "User has a dog named Rex", DEFAULT_EMBEDDING_PROVIDER);
    }

    @org.junit.jupiter.api.Nested
    class ParserTests {

        private final SemanticMemoryExtractor parserExtractor = new SemanticMemoryExtractor(
                null, null, null, new ObjectMapper(), null, null);

        @Test
        @DisplayName("extractFactsFromJson returns all facts from a thinking response with embedded JSON")
        void extractFactsFromJson_WhenThinkingResponseWithEmbeddedJson_ThenReturnsAllFacts() {
            String thinking = "Thus we have two facts: \"User's name is Luke\" and "
                    + "\"User is a software engineer\". The list is: "
                    + "[\"User's name is Luke\", \"User is a software engineer\"]";

            List<String> facts = parserExtractor.extractFactsFromJson(thinking);

            assertThat(facts).containsExactly("User's name is Luke", "User is a software engineer");
        }

        @Test
        @DisplayName("extractFactsFromJson returns all facts from a pure JSON array input")
        void extractFactsFromJson_WhenPureJsonArray_ThenReturnsAllFacts() {
            String pureJson = "[\"User's name is Luke\", \"User is a software engineer\"]";

            List<String> facts = parserExtractor.extractFactsFromJson(pureJson);

            assertThat(facts).containsExactly("User's name is Luke", "User is a software engineer");
        }

        @Test
        @DisplayName("extractFactsFromJson returns empty without throwing when input has no JSON array")
        void extractFactsFromJson_WhenNoJsonArrayAtAll_ThenReturnsEmptyAndDoesNotThrow() {
            String prose = "Thus we have two facts: User's name is Luke and User is a software engineer...";

            List<String> facts = parserExtractor.extractFactsFromJson(prose);

            assertThat(facts).isEmpty();
        }

        @Test
        @DisplayName("extractFactsFromJson extracts a single fact from a markdown-fenced JSON array")
        void extractFactsFromJson_WhenMarkdownFencedJson_ThenReturnsSingleFact() {
            String fenced = "```json\n[\"fact one\"]\n```";

            List<String> facts = parserExtractor.extractFactsFromJson(fenced);

            assertThat(facts).containsExactly("fact one");
        }
    }

    @Test
    @DisplayName("extract logs a WARN tally line when some fact insertions fail")
    void insertFactsWithTally_WhenSomeFail_ThenLogsWarnTallyLine() throws JsonProcessingException {
        // given — 2 facts, 2nd insert throws
        setupProviderConfig("meta-llama-3.1-8b-instruct");
        when(chatModelResolver.resolve(DEFAULT_PROVIDER)).thenReturn(chatModel);

        String jsonResponse = "[\"fact one\", \"fact two\"]";
        ChatResponse mockResponse = createMockChatResponse(jsonResponse);
        when(chatModel.call(any(Prompt.class))).thenReturn(mockResponse);
        when(chatResponseContentResolver.resolveContent(mockResponse)).thenReturn(jsonResponse);

        when(objectMapper.readValue(eq(jsonResponse), org.mockito.ArgumentMatchers.<TypeReference<List<String>>>any()))
                .thenReturn(List.of("fact one", "fact two"));

        doNothing().when(memoryClient).insertMemory(DEFAULT_USER_ID, "fact one", DEFAULT_EMBEDDING_PROVIDER);
        doThrow(new RuntimeException("boom"))
                .when(memoryClient).insertMemory(DEFAULT_USER_ID, "fact two", DEFAULT_EMBEDDING_PROVIDER);

        // attach captor to the SemanticMemoryExtractor logger
        Logger extractorLogger = (Logger) LoggerFactory.getLogger(SemanticMemoryExtractor.class);
        ListAppender<ILoggingEvent> appender = new ListAppender<>();
        appender.start();
        extractorLogger.addAppender(appender);

        try {
            // when
            extractor.extract(DEFAULT_USER_ID, DEFAULT_USER_TEXT, DEFAULT_PROVIDER, null, DEFAULT_EMBEDDING_PROVIDER);

            // then
            verify(memoryClient, timeout(2000)).insertMemory(DEFAULT_USER_ID, "fact two", DEFAULT_EMBEDDING_PROVIDER);
            // give virtual thread a moment to log after the failing insert
            verify(memoryClient, after(200).atLeastOnce()).insertMemory(DEFAULT_USER_ID, "fact one", DEFAULT_EMBEDDING_PROVIDER);

            assertThat(appender.list)
                    .anyMatch(e -> e.getLevel() == Level.WARN
                            && e.getFormattedMessage().contains("Inserted 1/2 facts for user '" + DEFAULT_USER_ID + "' (failed: 1)"));
        } finally {
            extractorLogger.detachAppender(appender);
        }
    }

    private void setupProviderConfig(String extractionModel) {
        ProviderConfig config = new ProviderConfig();
        config.setMemoryExtractionModel(extractionModel);
        when(aiProviderProperties.getProviders()).thenReturn(Map.of(DEFAULT_PROVIDER, config));
    }

    private ChatResponse createMockChatResponse(String content) {
        AssistantMessage assistantMessage = new AssistantMessage(content);
        Generation generation = new Generation(assistantMessage);
        return new ChatResponse(List.of(generation));
    }

    private ChatResponse createMockThinkingChatResponse(String thinkingContent, String actualContent) {
        Generation thinkingGeneration = new Generation(new AssistantMessage(thinkingContent));
        Generation actualGeneration = new Generation(new AssistantMessage(actualContent));
        return new ChatResponse(List.of(thinkingGeneration, actualGeneration));
    }
}
