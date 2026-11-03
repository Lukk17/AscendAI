"""Redis frontier of the crawl jobs (design D5 and D15).

Every shared-state change is one Redis Lua script, so several
ascend-web-hunter instances share one frontier with no lost update:

- ``SUBMIT_SCRIPT`` writes the job record, the seed queues, the seen set
  and the ``crawl_runnable`` member together.
- ``CLAIM_SCRIPT`` takes back expired claims, then refuses when the job is
  not claimable or pops one URL atomically with the in-flight counter, the
  crawl delay and the page budget held for all instances together. When the
  page budget is already reached and no claim is left, it moves the job to
  ``succeeded`` instead of leaving it in ``running`` with queued URLs.
- ``FINISH_SCRIPT`` removes the claim, appends the page line, counts the
  page, queues only unseen links and moves the job to ``succeeded`` when no
  queue and no claim is left, or when the page budget is reached and no
  claim is left even with queued URLs still waiting.
- ``CANCEL_SCRIPT`` moves a waiting or running job to ``cancelled`` and
  deletes its frontier keys.
- ``MARK_SCRIPT`` moves a job to ``failed`` with an error and deletes its
  frontier keys.
- ``ADD_SCRIPT`` queues sitemap URLs through the seen set.

Per-domain queue, in-flight and next-fetch keys are built inside the
scripts from the tenant, job and domain, because their count varies per
job. The fixed keys travel as ``KEYS``. The worker passes the current time
as ``now_ms`` so tests run under a fake clock. Queue and claim entries
read ``{depth}\\t{url}``.
"""

import redis.asyncio as redis

from src.crawl.keys import (
    RUNNABLE_KEY,
    claims_key,
    inflight_key,
    next_fetch_key,
    pages_key,
    queue_key,
    seen_key,
)

# cjson reads an empty JSON array back as an empty Lua table, which the
# encoder writes back as an empty JSON object. Every script below rewrites
# the job record, so each one pins both pattern lists to the array shape
# right after decoding, the same way CLAIM_SCRIPT already pins a missing
# claim_expiries to a map. `cjson.empty_array` is that marker on real Redis;
# the FakeRedis test double lacks it (nil), where a fresh table already
# encodes as an array.
_NORMALIZE_PATTERN_LISTS = """
local _request = job['request']
if _request ~= nil then
  local _empty_list = cjson.empty_array
  if _empty_list == nil then
    _empty_list = {}
  end
  local _include = _request['include_patterns']
  if type(_include) ~= 'table' or next(_include) == nil then
    _request['include_patterns'] = _empty_list
  end
  local _exclude = _request['exclude_patterns']
  if type(_exclude) ~= 'table' or next(_exclude) == nil then
    _request['exclude_patterns'] = _empty_list
  end
end
"""

SUBMIT_SCRIPT = (
    """
local job = cjson.decode(ARGV[1])
"""
    + _NORMALIZE_PATTERN_LISTS
    + """
local groups = cjson.decode(ARGV[5])
redis.call('SETEX', KEYS[1], ARGV[2], cjson.encode(job))
for _, group in ipairs(groups) do
  local qkey = 'crawl_queue:' .. ARGV[6] .. ':' .. ARGV[7] .. ':' .. group['domain']
  for _, item in ipairs(group['urls']) do
    redis.call('RPUSH', qkey, item['d'] .. '\\t' .. item['u'])
    redis.call('SADD', KEYS[2], item['u'])
  end
  redis.call('EXPIRE', qkey, ARGV[2])
end
redis.call('EXPIRE', KEYS[2], ARGV[2])
redis.call('ZADD', KEYS[3], ARGV[3], ARGV[4])
return {'ok'}
"""
)

CLAIM_SCRIPT = (
    """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return {'gone'}
end
local job = cjson.decode(raw)
"""
    + _NORMALIZE_PATTERN_LISTS
    + """
local state = job['state']
if state ~= 'waiting' and state ~= 'running' then
  return {'idle', state}
end
local now_ms = tonumber(ARGV[1])
local max_expiries = tonumber(ARGV[8])
local exps = job['claim_expiries']
if exps == nil then
  exps = {}
end
local expired = redis.call('ZRANGEBYSCORE', KEYS[4], 0, ARGV[1])
for _, entry in ipairs(expired) do
  local _, url = string.match(entry, '^(%d+)\\t(.*)$')
  redis.call('ZREM', KEYS[4], entry)
  local count = (exps[url] or 0) + 1
  if count >= max_expiries then
    exps[url] = nil
    job['counts']['failed'] = job['counts']['failed'] + 1
    job['pending'] = job['pending'] - 1
  else
    exps[url] = count
    redis.call('LPUSH', KEYS[2], entry)
    redis.call('DECR', KEYS[3])
    job['counts']['queued'] = job['counts']['queued'] + 1
  end
end
job['claim_expiries'] = exps
local done = job['counts']['fetched'] + job['counts']['unchanged'] + job['counts']['failed']
if done >= tonumber(ARGV[3]) then
  if redis.call('ZCARD', KEYS[4]) == 0 then
    job['state'] = 'succeeded'
    job['updated_at'] = ARGV[9]
    redis.call('SETEX', KEYS[1], ARGV[6], cjson.encode(job))
    redis.call('ZREM', KEYS[6], ARGV[7])
    return {'budget', 'succeeded'}
  end
  redis.call('SETEX', KEYS[1], ARGV[6], cjson.encode(job))
  return {'budget'}
end
local inflight = tonumber(redis.call('GET', KEYS[3]) or '0')
if inflight >= tonumber(ARGV[4]) then
  redis.call('SETEX', KEYS[1], ARGV[6], cjson.encode(job))
  return {'capped'}
end
local next_at = tonumber(redis.call('GET', KEYS[5]) or '0')
if next_at > now_ms then
  redis.call('SETEX', KEYS[1], ARGV[6], cjson.encode(job))
  return {'wait', next_at - now_ms}
end
local entry = redis.call('LPOP', KEYS[2])
if not entry then
  redis.call('SETEX', KEYS[1], ARGV[6], cjson.encode(job))
  return {'empty'}
end
local depth, url = string.match(entry, '^(%d+)\\t(.*)$')
redis.call('INCR', KEYS[3])
redis.call('EXPIRE', KEYS[3], ARGV[6])
redis.call('ZADD', KEYS[4], now_ms + tonumber(ARGV[2]), entry)
redis.call('EXPIRE', KEYS[4], ARGV[6])
redis.call('SET', KEYS[5], now_ms + tonumber(ARGV[5]))
redis.call('EXPIRE', KEYS[5], ARGV[6])
redis.call('EXPIRE', KEYS[2], ARGV[6])
job['counts']['queued'] = job['counts']['queued'] - 1
if state == 'waiting' then
  job['state'] = 'running'
end
job['updated_at'] = ARGV[9]
redis.call('SETEX', KEYS[1], ARGV[6], cjson.encode(job))
return {'claimed', url, depth}
"""
)

FINISH_SCRIPT = (
    """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return {'gone'}
end
local job = cjson.decode(raw)
"""
    + _NORMALIZE_PATTERN_LISTS
    + """
local state = job['state']
if state == 'cancelled' then
  return {'cancelled'}
end
if state ~= 'waiting' and state ~= 'running' then
  return {'stale', state}
end
if redis.call('ZSCORE', KEYS[3], ARGV[1]) == false then
  return {'stale'}
end
redis.call('ZREM', KEYS[3], ARGV[1])
local tenant = ARGV[7]
local job_id = ARGV[8]
local finished_domain = ARGV[9]
local inflight_key = 'crawl_inflight:' .. tenant .. ':' .. job_id .. ':' .. finished_domain
redis.call('DECR', inflight_key)
redis.call('EXPIRE', inflight_key, ARGV[5])
local outcome = ARGV[2]
if outcome == 'ok' then
  job['counts']['fetched'] = job['counts']['fetched'] + 1
elseif outcome == 'unchanged' then
  job['counts']['unchanged'] = job['counts']['unchanged'] + 1
else
  job['counts']['failed'] = job['counts']['failed'] + 1
end
job['counts']['skipped_unsafe'] = job['counts']['skipped_unsafe'] + tonumber(ARGV[6])
if ARGV[3] ~= '' then
  redis.call('RPUSH', KEYS[4], ARGV[3])
  redis.call('EXPIRE', KEYS[4], ARGV[5])
end
local max_depth = tonumber(ARGV[4])
local links = cjson.decode(ARGV[10])
for _, link in ipairs(links) do
  if link['d'] <= max_depth then
    if redis.call('SADD', KEYS[2], link['u']) == 1 then
      local qkey = 'crawl_queue:' .. tenant .. ':' .. job_id .. ':' .. link['domain']
      redis.call('RPUSH', qkey, link['d'] .. '\\t' .. link['u'])
      redis.call('EXPIRE', qkey, ARGV[5])
      job['counts']['queued'] = job['counts']['queued'] + 1
      job['pending'] = job['pending'] + 1
      local known = false
      for _, name in ipairs(job['domains']) do
        if name == link['domain'] then
          known = true
          break
        end
      end
      if not known then
        table.insert(job['domains'], link['domain'])
      end
    end
  end
end
redis.call('EXPIRE', KEYS[2], ARGV[5])
redis.call('EXPIRE', KEYS[3], ARGV[5])
job['pending'] = job['pending'] - 1
job['updated_at'] = ARGV[11]
local final = 'running'
local _done = job['counts']['fetched'] + job['counts']['unchanged'] + job['counts']['failed']
local _budget = nil
if job['request'] ~= nil and job['request']['page_budget'] ~= nil then
  _budget = tonumber(job['request']['page_budget'])
end
local _claims_left = redis.call('ZCARD', KEYS[3])
if job['pending'] <= 0 or (_budget ~= nil and _done >= _budget and _claims_left == 0) then
  job['state'] = 'succeeded'
  redis.call('ZREM', KEYS[5], ARGV[12])
  final = 'succeeded'
end
redis.call('SETEX', KEYS[1], ARGV[5], cjson.encode(job))
return {final}
"""
)

CANCEL_SCRIPT = (
    """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return {'gone'}
end
local job = cjson.decode(raw)
"""
    + _NORMALIZE_PATTERN_LISTS
    + """
local state = job['state']
if state ~= 'waiting' and state ~= 'running' then
  return {'idle', state}
end
local tenant = ARGV[3]
local job_id = ARGV[4]
for _, domain in ipairs(job['domains']) do
  redis.call('DEL', 'crawl_queue:' .. tenant .. ':' .. job_id .. ':' .. domain)
  redis.call('DEL', 'crawl_inflight:' .. tenant .. ':' .. job_id .. ':' .. domain)
  redis.call('DEL', 'crawl_next_fetch:' .. tenant .. ':' .. job_id .. ':' .. domain)
end
redis.call('DEL', KEYS[2])
redis.call('DEL', KEYS[3])
redis.call('DEL', KEYS[4])
redis.call('ZREM', KEYS[5], ARGV[5])
job['state'] = 'cancelled'
job['updated_at'] = ARGV[1]
redis.call('SETEX', KEYS[1], ARGV[2], cjson.encode(job))
return {'cancelled'}
"""
)

MARK_SCRIPT = (
    """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return {'gone'}
end
local job = cjson.decode(raw)
"""
    + _NORMALIZE_PATTERN_LISTS
    + """
local state = job['state']
if state ~= 'waiting' and state ~= 'running' then
  return {'idle', state}
end
local tenant = ARGV[4]
local job_id = ARGV[5]
for _, domain in ipairs(job['domains']) do
  redis.call('DEL', 'crawl_queue:' .. tenant .. ':' .. job_id .. ':' .. domain)
  redis.call('DEL', 'crawl_inflight:' .. tenant .. ':' .. job_id .. ':' .. domain)
  redis.call('DEL', 'crawl_next_fetch:' .. tenant .. ':' .. job_id .. ':' .. domain)
end
redis.call('DEL', KEYS[2])
redis.call('DEL', KEYS[3])
redis.call('DEL', KEYS[4])
redis.call('ZREM', KEYS[5], ARGV[6])
job['state'] = 'failed'
job['error'] = ARGV[3]
job['updated_at'] = ARGV[1]
redis.call('SETEX', KEYS[1], ARGV[2], cjson.encode(job))
return {'failed'}
"""
)

ADD_SCRIPT = (
    """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return {'gone'}
end
local job = cjson.decode(raw)
"""
    + _NORMALIZE_PATTERN_LISTS
    + """
local state = job['state']
if state ~= 'waiting' and state ~= 'running' then
  return {'idle', state}
end
local tenant = ARGV[3]
local job_id = ARGV[4]
local added = 0
local links = cjson.decode(ARGV[5])
for _, link in ipairs(links) do
  if redis.call('SADD', KEYS[2], link['u']) == 1 then
    local qkey = 'crawl_queue:' .. tenant .. ':' .. job_id .. ':' .. link['domain']
    redis.call('RPUSH', qkey, link['d'] .. '\\t' .. link['u'])
    redis.call('EXPIRE', qkey, ARGV[2])
    job['counts']['queued'] = job['counts']['queued'] + 1
    job['pending'] = job['pending'] + 1
    added = added + 1
    local known = false
    for _, name in ipairs(job['domains']) do
      if name == link['domain'] then
        known = true
        break
      end
    end
    if not known then
      table.insert(job['domains'], link['domain'])
    end
  end
end
redis.call('EXPIRE', KEYS[2], ARGV[2])
job['updated_at'] = ARGV[1]
redis.call('SETEX', KEYS[1], ARGV[2], cjson.encode(job))
return {'added', added}
"""
)


SET_INDEX_SCRIPT = (
    """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return {'gone'}
end
local job = cjson.decode(raw)
"""
    + _NORMALIZE_PATTERN_LISTS
    + """
if job['state'] ~= 'succeeded' then
  return {'idle', job['state']}
end
job['pages_ndjson_key'] = ARGV[3]
job['updated_at'] = ARGV[1]
redis.call('SETEX', KEYS[1], ARGV[2], cjson.encode(job))
return {'ok'}
"""
)


class Frontier:
    """One shared crawl frontier over a Redis client.

    Every change of shared state is one ``EVAL`` of the scripts above, so
    two instances never claim the same URL and the caps hold for all of
    them together. Plain reads and the final key deletion after the object
    write are not scripts: they change no job record.
    """

    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    async def submit(
        self,
        *,
        job_key: str,
        seen_key: str,
        runnable_key: str,
        job_json: str,
        retention: int,
        submitted_ms: int,
        member: str,
        tenant_id: str,
        job_id: str,
        groups_json: str,
    ) -> list[str]:
        return list(
            await self._client.eval(
                SUBMIT_SCRIPT,
                3,
                job_key,
                seen_key,
                runnable_key,
                job_json,
                retention,
                submitted_ms,
                member,
                groups_json,
                tenant_id,
                job_id,
            )
        )

    async def claim(
        self,
        *,
        job_key: str,
        queue_key: str,
        inflight_key: str,
        claims_key: str,
        next_fetch_key: str,
        runnable_key: str,
        now_ms: int,
        lease_ms: int,
        page_budget: int,
        domain_cap: int,
        delay_ms: int,
        retention: int,
        member: str,
        max_expiries: int,
        updated_at: str,
    ) -> list[str]:
        raw = await self._client.eval(
            CLAIM_SCRIPT,
            6,
            job_key,
            queue_key,
            inflight_key,
            claims_key,
            next_fetch_key,
            runnable_key,
            now_ms,
            lease_ms,
            page_budget,
            domain_cap,
            delay_ms,
            retention,
            member,
            max_expiries,
            updated_at,
        )
        return [str(item) for item in raw]

    async def finish(
        self,
        *,
        job_key: str,
        seen_key: str,
        claims_key: str,
        pages_key: str,
        runnable_key: str,
        entry: str,
        outcome: str,
        page_line: str,
        max_depth: int,
        retention: int,
        skipped_delta: int,
        tenant_id: str,
        job_id: str,
        domain: str,
        links_json: str,
        updated_at: str,
        member: str,
    ) -> list[str]:
        raw = await self._client.eval(
            FINISH_SCRIPT,
            5,
            job_key,
            seen_key,
            claims_key,
            pages_key,
            runnable_key,
            entry,
            outcome,
            page_line,
            max_depth,
            retention,
            skipped_delta,
            tenant_id,
            job_id,
            domain,
            links_json,
            updated_at,
            member,
        )
        return [str(item) for item in raw]

    async def cancel(
        self,
        *,
        job_key: str,
        seen_key: str,
        claims_key: str,
        pages_key: str,
        runnable_key: str,
        updated_at: str,
        retention: int,
        tenant_id: str,
        job_id: str,
        member: str,
    ) -> list[str]:
        raw = await self._client.eval(
            CANCEL_SCRIPT,
            5,
            job_key,
            seen_key,
            claims_key,
            pages_key,
            runnable_key,
            updated_at,
            retention,
            tenant_id,
            job_id,
            member,
        )
        return [str(item) for item in raw]

    async def mark_failed(
        self,
        *,
        job_key: str,
        seen_key: str,
        claims_key: str,
        pages_key: str,
        runnable_key: str,
        updated_at: str,
        retention: int,
        error: str,
        tenant_id: str,
        job_id: str,
        member: str,
    ) -> list[str]:
        raw = await self._client.eval(
            MARK_SCRIPT,
            5,
            job_key,
            seen_key,
            claims_key,
            pages_key,
            runnable_key,
            updated_at,
            retention,
            error,
            tenant_id,
            job_id,
            member,
        )
        return [str(item) for item in raw]

    async def add_urls(
        self,
        *,
        job_key: str,
        seen_key: str,
        updated_at: str,
        retention: int,
        tenant_id: str,
        job_id: str,
        links_json: str,
    ) -> list[str]:
        raw = await self._client.eval(
            ADD_SCRIPT,
            2,
            job_key,
            seen_key,
            updated_at,
            retention,
            tenant_id,
            job_id,
            links_json,
        )
        return [str(item) for item in raw]

    async def set_index_key(
        self,
        *,
        job_key: str,
        updated_at: str,
        retention: int,
        index_key: str,
    ) -> list[str]:
        raw = await self._client.eval(
            SET_INDEX_SCRIPT,
            1,
            job_key,
            updated_at,
            retention,
            index_key,
        )
        return [str(item) for item in raw]

    async def list_runnable(self) -> list[str]:
        members = await self._client.zrange(RUNNABLE_KEY, 0, -1)
        return [str(item) for item in members]

    async def remove_runnable_member(self, member: str) -> None:
        await self._client.zrem(RUNNABLE_KEY, member)

    async def read_pages(self, pages_key: str) -> list[str]:
        lines = await self._client.lrange(pages_key, 0, -1)
        return [str(item) for item in lines]

    async def delete_frontier(self, tenant_id: str, job_id: str, domains: list[str]) -> None:
        keys = (
            [queue_key(tenant_id, job_id, domain) for domain in domains]
            + [inflight_key(tenant_id, job_id, domain) for domain in domains]
            + [next_fetch_key(tenant_id, job_id, domain) for domain in domains]
            + [
                seen_key(tenant_id, job_id),
                claims_key(tenant_id, job_id),
                pages_key(tenant_id, job_id),
            ]
        )
        await self._client.delete(*keys)
