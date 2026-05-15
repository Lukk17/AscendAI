-- Compaction "fires + replaces prefix" seed.
-- Inserts 21 rows for user 'compaction-fires-test' alternating user/assistant.
-- USER turns sprinkle 4 distinct, easily-greppable facts so the cheap model
-- has actual content to compress. ASSISTANT turns are short generic
-- acknowledgements. Topics drift across the 21 turns.
--
-- Spec: AscendAgent/e2e/testing/10-compaction-fires-test.md
-- Apply: docker exec -i postgres psql -U postgres -d ascend_ai < seed-compaction-fires.sql
-- Reset before applying: DELETE FROM chat_history WHERE user_id = 'compaction-fires-test';

DELETE FROM chat_history WHERE user_id = 'compaction-fires-test';

INSERT INTO chat_history (user_id, role, content, created_at) VALUES
  ('compaction-fires-test', 'user',      'Hi! My dog Rex is a beagle and he loves chasing squirrels in the backyard.', NOW() - INTERVAL '21 minute'),
  ('compaction-fires-test', 'assistant', 'Got it.',                                                                        NOW() - INTERVAL '20 minute'),
  ('compaction-fires-test', 'user',      'I''m based in Warsaw and the weather has been awful this week.',                 NOW() - INTERVAL '19 minute'),
  ('compaction-fires-test', 'assistant', 'Acknowledged.',                                                                   NOW() - INTERVAL '18 minute'),
  ('compaction-fires-test', 'user',      'Rex slipped on the wet floor yesterday but he''s fine now.',                     NOW() - INTERVAL '17 minute'),
  ('compaction-fires-test', 'assistant', 'Glad to hear it.',                                                                NOW() - INTERVAL '16 minute'),
  ('compaction-fires-test', 'user',      'I work as a backend engineer at TechCorp.',                                       NOW() - INTERVAL '15 minute'),
  ('compaction-fires-test', 'assistant', 'Noted.',                                                                          NOW() - INTERVAL '14 minute'),
  ('compaction-fires-test', 'user',      'My favorite framework is Spring Boot — I use it daily.',                          NOW() - INTERVAL '13 minute'),
  ('compaction-fires-test', 'assistant', 'Understood.',                                                                     NOW() - INTERVAL '12 minute'),
  ('compaction-fires-test', 'user',      'We had a deploy fail at TechCorp last Tuesday because of a bad Liquibase change.', NOW() - INTERVAL '11 minute'),
  ('compaction-fires-test', 'assistant', 'Tough one.',                                                                      NOW() - INTERVAL '10 minute'),
  ('compaction-fires-test', 'user',      'Rex needs his vaccinations updated next month at the Warsaw clinic.',             NOW() - INTERVAL '9 minute'),
  ('compaction-fires-test', 'assistant', 'Marked.',                                                                         NOW() - INTERVAL '8 minute'),
  ('compaction-fires-test', 'user',      'I''ve been considering migrating one of our services from Spring Boot to Quarkus.', NOW() - INTERVAL '7 minute'),
  ('compaction-fires-test', 'assistant', 'Interesting trade-off.',                                                          NOW() - INTERVAL '6 minute'),
  ('compaction-fires-test', 'user',      'My commute to the TechCorp office in central Warsaw takes about 35 minutes.',     NOW() - INTERVAL '5 minute'),
  ('compaction-fires-test', 'assistant', 'Got it.',                                                                         NOW() - INTERVAL '4 minute'),
  ('compaction-fires-test', 'user',      'Rex was actually a rescue from a shelter in Praga.',                              NOW() - INTERVAL '3 minute'),
  ('compaction-fires-test', 'assistant', 'That''s lovely.',                                                                 NOW() - INTERVAL '2 minute'),
  ('compaction-fires-test', 'user',      'Anyway, switching topics — can you remind me what I told you so far?',            NOW() - INTERVAL '1 minute');
