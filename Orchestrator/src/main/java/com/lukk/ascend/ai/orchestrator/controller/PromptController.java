package com.lukk.ascend.ai.orchestrator.controller;

import com.lukk.ascend.ai.orchestrator.config.api.ApiCommonErrorResponses;
import com.lukk.ascend.ai.orchestrator.config.api.ApiCommonSuccessResponses;
import com.lukk.ascend.ai.orchestrator.dto.AiResponse;
import com.lukk.ascend.ai.orchestrator.dto.PromptRequest;
import com.lukk.ascend.ai.orchestrator.service.AiConnectionService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Slf4j
@RestController
@RequiredArgsConstructor
@Tag(name = "Prompt", description = "Prompt controller.")
@RequestMapping(produces = "application/json")
public class PromptController {

    private final AiConnectionService aiConnectionService;

    @Value("${app.user.default-id:user1}")
    private String defaultUserId;

    @Operation(
            summary = "AscendAI prompt endpoint",
            description = "Process user prompt with AI."
    )
    @ApiCommonSuccessResponses
    @ApiCommonErrorResponses
    @PostMapping("/prompt")
    public ResponseEntity<AiResponse> getAiResponse(@RequestBody PromptRequest promptRequest) {
        log.info("Prompt: '{}', UserID: '{}'", promptRequest.prompt(), defaultUserId);
        return ResponseEntity.ok(aiConnectionService.prompt(promptRequest.prompt(), defaultUserId));
    }
}
