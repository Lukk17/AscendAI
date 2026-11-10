"""Redis frontier of the crawl jobs.

Every shared-state change is one Redis Lua script, so several
ascend-web-hunter instances share one frontier with no lost update:

- ``SUBMIT_SCRIPT`` writes the job record, the seed queues, the seen set
  and the ``crawl_runnable`` member together.
- ``CLAIM_SCRIPT`` takes back expired claims into the queue and in-flight
  counter of the domain each claim names, then refuses when the job is not
  claimable or pops one URL atomically with the in-flight counter, the crawl
  delay and the page budget held for all instances together. Claims in
  flight count against the page budget. When the page budget is reached and
  no claim is left, or the last URL fails by expiry, it ends the job.
- ``FINISH_SCRIPT`` removes the claim, written with its domain or in the
  older ``{depth}\\t{url}`` form, appends the page line, counts the
  page, queues only unseen links and ends the job when no queue and no claim
  is left, or when the page budget is reached and no claim is left even with
  queued URLs still waiting. A page skipped for robots.txt has its own count
  and spends no page budget, but a job also ends once those skips reach the
  page budget times ``robots_skip_factor``, in this script and in ``CLAIM_SCRIPT``.
- A job ends ``failed`` when no page of it was fetched or unchanged, and
  ``succeeded`` otherwise.
- ``CANCEL_SCRIPT`` moves a waiting or running job to ``cancelled`` and
  deletes its frontier keys.
- ``ADD_SCRIPT`` queues sitemap URLs through the seen set.
- ``EXTEND_NEXT_FETCH_SCRIPT`` moves a domain's next fetch time later, never
  earlier, when the claimed URL's origin asks a longer crawl delay.

Per-domain queue, in-flight and next-fetch keys are built inside the
scripts from the tenant, job and domain, because their count varies per
job. The fixed keys travel as ``KEYS``. The worker passes the current time
as ``now_ms`` so tests run under a fake clock. Queue entries read
``{depth}\\t{url}`` and claim entries ``{depth}\\t{domain}\\t{url}``.
Every script that rewrites the job record first writes an empty or missing
``include_patterns`` and ``exclude_patterns`` back as a JSON array, using
``cjson.empty_array`` where the Redis build provides it.
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

ALL_PAGES_FAILED_ERROR = "every page of the job failed"

_END_JOB = (
    """
local function end_job(job, runnable_key, member)
  local final = 'succeeded'
  if job['counts']['fetched'] + job['counts']['unchanged'] == 0 then
    final = 'failed'
    job['error'] = '"""
    + ALL_PAGES_FAILED_ERROR
    + """'
  end
  job['state'] = final
  redis.call('ZREM', runnable_key, member)
  return final
end
"""
)

CLAIM_SCRIPT = (
    _END_JOB
    + """
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
local retention = ARGV[6]
local tenant = ARGV[10]
local job_id = ARGV[11]
local claim_domain = ARGV[12]
local exps = job['claim_expiries']
if exps == nil then
  exps = {}
end
local changed = false
local expired = redis.call('ZRANGEBYSCORE', KEYS[4], 0, ARGV[1])
for _, entry in ipairs(expired) do
  changed = true
  redis.call('ZREM', KEYS[4], entry)
  local depth, owner, url = string.match(entry, '^(%d+)\t([^\t]+)\t(.*)$')
  local owner_queue = KEYS[2]
  local owner_inflight = KEYS[3]
  if depth == nil then
    depth, url = string.match(entry, '^(%d+)\t(.*)$')
  else
    owner_queue = 'crawl_queue:' .. tenant .. ':' .. job_id .. ':' .. owner
    owner_inflight = 'crawl_inflight:' .. tenant .. ':' .. job_id .. ':' .. owner
  end
  redis.call('DECR', owner_inflight)
  redis.call('EXPIRE', owner_inflight, retention)
  local count = (exps[url] or 0) + 1
  if count >= max_expiries then
    exps[url] = nil
    job['counts']['failed'] = job['counts']['failed'] + 1
    job['pending'] = job['pending'] - 1
  else
    exps[url] = count
    redis.call('LPUSH', owner_queue, depth .. '\t' .. url)
    redis.call('EXPIRE', owner_queue, retention)
    job['counts']['queued'] = job['counts']['queued'] + 1
  end
end
job['claim_expiries'] = exps
local function save_if_changed()
  if changed then
    job['updated_at'] = ARGV[9]
    redis.call('SETEX', KEYS[1], retention, cjson.encode(job))
  end
end
if changed and job['pending'] <= 0 then
  job['updated_at'] = ARGV[9]
  local final = end_job(job, KEYS[6], ARGV[7])
  redis.call('SETEX', KEYS[1], retention, cjson.encode(job))
  return {'ended', final}
end
local in_flight = redis.call('ZCARD', KEYS[4])
local done = job['counts']['fetched'] + job['counts']['unchanged'] + job['counts']['failed']
local budget = tonumber(ARGV[3])
local robots_skipped = job['counts']['robots_skipped'] or 0
if done + in_flight >= budget or robots_skipped >= budget * tonumber(ARGV[13]) then
  if in_flight == 0 then
    job['updated_at'] = ARGV[9]
    local final = end_job(job, KEYS[6], ARGV[7])
    redis.call('SETEX', KEYS[1], retention, cjson.encode(job))
    return {'budget', final}
  end
  save_if_changed()
  return {'budget'}
end
local inflight = tonumber(redis.call('GET', KEYS[3]) or '0')
if inflight >= tonumber(ARGV[4]) then
  save_if_changed()
  return {'capped'}
end
local next_at = tonumber(redis.call('GET', KEYS[5]) or '0')
if next_at > now_ms then
  save_if_changed()
  return {'wait', next_at - now_ms}
end
local entry = redis.call('LPOP', KEYS[2])
if not entry then
  save_if_changed()
  return {'empty'}
end
local depth, url = string.match(entry, '^(%d+)\t(.*)$')
redis.call('INCR', KEYS[3])
redis.call('EXPIRE', KEYS[3], retention)
redis.call('ZADD', KEYS[4], now_ms + tonumber(ARGV[2]), depth .. '\t' .. claim_domain .. '\t' .. url)
redis.call('EXPIRE', KEYS[4], retention)
redis.call('SET', KEYS[5], now_ms + tonumber(ARGV[5]))
redis.call('EXPIRE', KEYS[5], retention)
redis.call('EXPIRE', KEYS[2], retention)
job['counts']['queued'] = job['counts']['queued'] - 1
if state == 'waiting' then
  job['state'] = 'running'
end
job['updated_at'] = ARGV[9]
redis.call('SETEX', KEYS[1], retention, cjson.encode(job))
return {'claimed', url, depth}
"""
)

FINISH_SCRIPT = (
    _END_JOB
    + """
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
local claim = ARGV[1]
if redis.call('ZSCORE', KEYS[3], claim) == false then
  local claim_depth, _, claim_url = string.match(claim, '^(%d+)\t([^\t]+)\t(.*)$')
  if claim_depth == nil then
    return {'stale'}
  end
  claim = claim_depth .. '\t' .. claim_url
  if redis.call('ZSCORE', KEYS[3], claim) == false then
    return {'stale'}
  end
end
redis.call('ZREM', KEYS[3], claim)
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
elseif outcome == 'robots_skipped' then
  job['counts']['robots_skipped'] = (job['counts']['robots_skipped'] or 0) + 1
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
local _skipped = job['counts']['robots_skipped'] or 0
local _ceiling_reached = _budget ~= nil and (_done >= _budget or _skipped >= _budget * tonumber(ARGV[13]))
if job['pending'] <= 0 or (_ceiling_reached and _claims_left == 0) then
  final = end_job(job, KEYS[5], ARGV[12])
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

EXTEND_NEXT_FETCH_SCRIPT = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if tonumber(ARGV[1]) > current then
  redis.call('SET', KEYS[1], ARGV[1])
end
redis.call('EXPIRE', KEYS[1], ARGV[2])
return {'ok'}
"""


def claim_entry(depth: int | str, domain: str, url: str) -> str:
    return f"{depth}\t{domain}\t{url}"


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
        tenant_id: str,
        job_id: str,
        domain: str,
        robots_skip_factor: int,
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
            tenant_id,
            job_id,
            domain,
            robots_skip_factor,
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
        robots_skip_factor: int,
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
            robots_skip_factor,
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

    async def extend_next_fetch(self, *, next_fetch_key: str, next_fetch_ms: int, retention: int) -> None:
        await self._client.eval(EXTEND_NEXT_FETCH_SCRIPT, 1, next_fetch_key, next_fetch_ms, retention)

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
