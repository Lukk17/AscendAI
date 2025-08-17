package com.lukk.ai.orchestrator.controller;

import com.lukk.ai.orchestrator.dto.AiResponse;
import com.lukk.ai.orchestrator.dto.PromptRequest;
import com.lukk.ai.orchestrator.service.AiConnectionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
@Slf4j
public class PromptController {

    private final AiConnectionService aiConnectionService;

    @PostMapping("/prompt")
    public ResponseEntity<AiResponse>
    getAiResponse(@RequestBody PromptRequest promptRequest) {
        log.info("Prompt: '{}'", promptRequest.prompt());
        return ResponseEntity.ok(aiConnectionService.prompt(promptRequest.prompt()));
    }
}
