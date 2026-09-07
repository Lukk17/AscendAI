package com.lukk.ascend.ai.agent.model;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.springframework.data.annotation.Id;
import org.springframework.data.relational.core.mapping.Table;

import java.time.LocalDateTime;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Table("user_instructions")
public class UserInstruction {
    @Id
    private String userId;
    private String instructionText;
    private LocalDateTime updatedAt;
}
