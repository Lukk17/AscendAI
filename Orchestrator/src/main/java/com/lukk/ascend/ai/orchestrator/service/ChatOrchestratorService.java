package com.lukk.ascend.ai.orchestrator.service;

import com.lukk.ascend.ai.orchestrator.dto.AiResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.messages.Message;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

@Service
@RequiredArgsConstructor
@Slf4j
public class ChatOrchestratorService {

    private final ChatContextAssembler contextAssembler;
    private final ChatHistoryService historyService;
    private final ChatExecutor chatExecutor;

    public AiResponse prompt(String prompt, MultipartFile image, MultipartFile document, String userId,
                             String provider, String model) {
        log.info("Starting orchestration for user: {}", userId);

        String systemText = contextAssembler.buildSystemMessage(userId, prompt);
        String userText = contextAssembler.buildUserMessage(prompt, document, provider);

        List<Message> history = historyService.loadHistory(userId);

        AiResponse response = chatExecutor.execute(userId, systemText, userText, history, image, provider, model);

        historyService.saveHistory(userId, userText, response.content());

        return response;
    }
}
