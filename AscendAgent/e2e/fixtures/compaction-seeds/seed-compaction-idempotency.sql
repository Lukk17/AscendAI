-- Compaction "idempotency" seed.
-- Pre-seeds the post-compaction state: 1 [Conversation summary] system row +
-- 8 raw turns (4 user + 4 assistant). That's exactly 9 rows, mimicking the
-- result of a previous compaction run.
--
-- Spec: AscendAgent/e2e/testing/11-compaction-idempotency-test.md
-- Apply: docker exec -i postgres psql -U postgres -d ascend_ai < seed-compaction-idempotency.sql
-- Reset before applying: DELETE FROM chat_history WHERE user_id = 'compaction-idempotency-test';

DELETE FROM chat_history WHERE user_id = 'compaction-idempotency-test';

-- The single summary row (oldest entry — would be replaced if compaction fired again)
INSERT INTO chat_history (user_id, role, content, created_at) VALUES
  ('compaction-idempotency-test', 'system',
   '[Conversation summary] User has a beagle named Rex (rescued from a Praga shelter), is based in Warsaw, works as a backend engineer at TechCorp, and prefers Spring Boot but is considering Quarkus for one service. Rex slipped on a wet floor recently but is fine; vaccinations due next month at the Warsaw clinic.',
   NOW() - INTERVAL '60 minute');

-- The 8 most-recent raw turns (4 user + 4 assistant alternating)
INSERT INTO chat_history (user_id, role, content, created_at) VALUES
  ('compaction-idempotency-test', 'user',      'Quick follow-up — what was the name of my dog again?',                NOW() - INTERVAL '8 minute'),
  ('compaction-idempotency-test', 'assistant', 'Your dog is Rex, a beagle.',                                          NOW() - INTERVAL '7 minute'),
  ('compaction-idempotency-test', 'user',      'And which city am I in?',                                             NOW() - INTERVAL '6 minute'),
  ('compaction-idempotency-test', 'assistant', 'You mentioned you''re based in Warsaw.',                              NOW() - INTERVAL '5 minute'),
  ('compaction-idempotency-test', 'user',      'Right. What framework do I prefer at work?',                          NOW() - INTERVAL '4 minute'),
  ('compaction-idempotency-test', 'assistant', 'Spring Boot — though you said you''re evaluating Quarkus for one service.', NOW() - INTERVAL '3 minute'),
  ('compaction-idempotency-test', 'user',      'Good memory. Where do I work?',                                       NOW() - INTERVAL '2 minute'),
  ('compaction-idempotency-test', 'assistant', 'You work as a backend engineer at TechCorp.',                         NOW() - INTERVAL '1 minute');
