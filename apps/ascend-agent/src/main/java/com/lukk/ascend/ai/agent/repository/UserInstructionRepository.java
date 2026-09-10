package com.lukk.ascend.ai.agent.repository;

import com.lukk.ascend.ai.agent.model.UserInstruction;
import org.springframework.data.repository.CrudRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface UserInstructionRepository extends CrudRepository<UserInstruction, String> {
}
