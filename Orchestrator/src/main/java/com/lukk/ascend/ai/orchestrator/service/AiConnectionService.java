package com.lukk.ascend.ai.orchestrator.service;

import com.lukk.ascend.ai.orchestrator.dto.AiResponse;
import com.lukk.ascend.ai.orchestrator.exception.AiGenerationException;
import com.lukk.ascend.ai.orchestrator.memory.PersistentChatMemory;
import com.lukk.ascend.ai.orchestrator.service.ingestion.IngestionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.client.ChatClient.ChatClientRequestSpec;
import org.springframework.ai.chat.client.advisor.vectorstore.QuestionAnswerAdvisor;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.client.advisor.SimpleLoggerAdvisor;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.PromptTemplate;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.InputStreamResource;
import org.springframework.core.io.Resource;
import org.springframework.stereotype.Service;
import org.springframework.util.MimeTypeUtils;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.Map;

@Service
@RequiredArgsConstructor
@Slf4j
public class AiConnectionService {

    public static final String USER_ID_KEY = "user_id";
    private final ChatClient chatClient;
    private final VectorStore vectorStore;
    private final IngestionService ingestionService;
    private final UserInstructionService userInstructionService;
    private final PersistentChatMemory persistentChatMemory;

    private static final int RAG_SEARCH_RESULT_LIMIT = 5;

    @Value("${app.system-prompt}")
    private String baseSystemPrompt;

    public AiResponse prompt(String prompt, MultipartFile image, MultipartFile document, String userId) {
        String instructions = userInstructionService.getInstructions(userId);
        log.info("Loaded instructions for user: {}", userId);

        List<Message> history = persistentChatMemory.get(userId, 100);
        log.info("Loaded chat history for user: {}, size: {}", userId, history.size());

        String userPrompt = prompt;
        if (document != null && !document.isEmpty()) {
            userPrompt += "\n\n<document_context>\n" + fetchAndProcessDocument(document) + "\n</document_context>\n";
            log.info("Processed document context for file: {}", document.getOriginalFilename());
        }

        ChatClient.ChatClientRequestSpec promptBuilder = chatClient.prompt()
                .system(s -> s.text(baseSystemPrompt + "\n\nUser Instructions:\n" + instructions))
                .messages(history)
                // makes model not to use any tools
//                .advisors(createRagAdvisor(userPrompt))
                .advisors(new SimpleLoggerAdvisor())
                .advisors(a -> a.param(USER_ID_KEY, userId));

        promptBuilder.toolContext(Map.of(USER_ID_KEY, userId));

        handleImageContext(promptBuilder, userPrompt, image);

        log.info("Executing AI Prompt | User: {} | Prompt: {}", userId, prompt);
        ChatResponse chatResponse = promptBuilder.call().chatResponse();

        if (chatResponse == null) {
            throw new AiGenerationException("Received null response from ChatClient");
        }

        String content = chatResponse.getResult().getOutput().getText();

        updateMemory(userId, prompt, content, image != null && !image.isEmpty());

        return new AiResponse(content, chatResponse.getMetadata());
    }

    private QuestionAnswerAdvisor createRagAdvisor(String userPrompt) {
        SearchRequest searchRequest = SearchRequest.builder()
                .query(userPrompt)
                .topK(RAG_SEARCH_RESULT_LIMIT)
                .build();

        return QuestionAnswerAdvisor.builder(vectorStore)
                .searchRequest(searchRequest)
                .build();
    }

    private void handleImageContext(ChatClientRequestSpec promptBuilder,
            String userPrompt, MultipartFile image) {
        if (image != null && !image.isEmpty()) {
            try {
                Resource imageResource = new InputStreamResource(image.getInputStream());
                promptBuilder.user(u -> u.text(userPrompt).media(MimeTypeUtils.IMAGE_PNG, imageResource));
                log.info("Attached image resource to prompt");
            } catch (Exception e) {
                throw new AiGenerationException("Failed to process image upload", e);
            }
        } else {
            promptBuilder.user(userPrompt);
        }
    }

    private void updateMemory(String userId, String userPrompt, String content, boolean hasImage) {
        log.info("Saving chat history for User: {}", userId);
        Message userMsg = new UserMessage(userPrompt);
        Message assistantMsg = new AssistantMessage(content);
        persistentChatMemory.add(userId, List.of(userMsg, assistantMsg));
        log.info("Successfully saved history for User: {}", userId);
    }

    private String fetchAndProcessDocument(MultipartFile file) {
        try (var inputStream = file.getInputStream()) {
            String filename = file.getOriginalFilename() != null ? file.getOriginalFilename() : "document";
            List<Document> documents = filename.endsWith(".md")
                    ? ingestionService.processMarkdown(inputStream, filename)
                    : ingestionService.processUnstructured(inputStream, filename);

            return documents.stream()
                    .map(Document::getText)
                    .reduce("", (a, b) -> a + "\n" + b);
        } catch (Exception e) {
            throw new AiGenerationException("Failed to process document context: " + file.getOriginalFilename(), e);
        }
    }
}
