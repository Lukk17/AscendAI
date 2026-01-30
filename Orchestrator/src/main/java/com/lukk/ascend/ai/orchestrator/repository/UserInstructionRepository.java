package com.lukk.ascend.ai.orchestrator.repository;

import com.lukk.ascend.ai.orchestrator.model.UserInstruction;
import org.springframework.data.repository.CrudRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface UserInstructionRepository extends CrudRepository<UserInstruction, String> {
}
