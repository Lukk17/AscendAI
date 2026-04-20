package com.lukk.ascend.ai.orchestrator.model;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.springframework.data.annotation.Id;
import org.springframework.data.relational.core.mapping.Table;

import java.time.LocalDateTime;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Table("chat_history")
public class ChatHistory {
    @Id
    private Long id;
    private String userId;
    private String role;
    private String content;
    private LocalDateTime createdAt;
}
