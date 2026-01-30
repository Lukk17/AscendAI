package com.lukk.ascend.ai.orchestrator.repository;

import com.lukk.ascend.ai.orchestrator.model.ChatHistory;
import org.springframework.data.jdbc.repository.query.Query;
import org.springframework.data.repository.CrudRepository;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface ChatHistoryRepository extends CrudRepository<ChatHistory, Long> {

    @Query("SELECT * FROM chat_history WHERE user_id = :userId ORDER BY created_at DESC LIMIT :limit")
    List<ChatHistory> findRecentHistory(@Param("userId") String userId, @Param("limit") int limit);
}
