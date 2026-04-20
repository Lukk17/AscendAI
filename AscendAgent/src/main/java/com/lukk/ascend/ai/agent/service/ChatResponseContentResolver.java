package com.lukk.ascend.ai.agent.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.List;
import java.util.ListIterator;
import java.util.Optional;

@Service
@Slf4j
public class ChatResponseContentResolver {

    public String resolveContent(ChatResponse chatResponse) {
        return Optional.ofNullable(chatResponse)
                .map(ChatResponse::getResults)
                .flatMap(this::findLastNonBlankText)
                .orElse("");
    }

    private Optional<String> findLastNonBlankText(List<Generation> generations) {
        ListIterator<Generation> iterator = generations.listIterator(generations.size());
        while (iterator.hasPrevious()) {
            String text = extractText(iterator.previous());
            if (StringUtils.hasText(text)) {
                return Optional.of(text);
            }
        }
        return Optional.empty();
    }

    private String extractText(Generation generation) {
        return Optional.ofNullable(generation)
                .map(Generation::getOutput)
                .map(output -> output.getText())
                .orElse(null);
    }
}
