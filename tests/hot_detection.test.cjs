const {test} = require('node:test');
const assert = require('node:assert/strict');
const {dateKey, isToday, withinHours} = require('../web/hot-detection.js');
const {compare, consumed} = require('../web/hot-detection.js');
const ts = iso => Date.parse(iso) / 1000;
test('Korean midnight separates today from yesterday', () => {
  const midnight = ts('2026-09-26T15:00:00Z');
  assert.equal(dateKey(midnight), '2026-09-27');
  assert.equal(dateKey(midnight - 1), '2026-09-26');
  assert.equal(isToday({tier: 1, hot_detected_at: midnight}, midnight + 1), true);
  assert.equal(isToday({tier: 3, hot_detected_at: midnight - 1}, midnight + 1), false);
});
test('today comes before higher scored history for all selected sorts', () => {
  const now = ts('2026-10-04T15:00:00Z');
  const old = {tier:3, hot_detected_at:now-1, rank_score:100, taken_at:now-10};
  const fresh = {tier:1, hot_detected_at:now, rank_score:1, taken_at:now-100};
  assert.deepEqual([old, fresh].sort((a,b)=>compare(a,b,p=>p.rank_score,now)), [fresh,old]);
  assert.equal(consumed(old,now),true);
  assert.equal(consumed(fresh,now),false);
  assert.equal(consumed({tier:3},now),true);
});
test('old publication may be newly hot; normal and undated posts are excluded', () => {
  const now = ts('2026-09-27T01:00:00Z');
  assert.equal(isToday({tier: 1, age_hours: 500, hot_detected_at: now}, now), true);
  assert.equal(isToday({tier: 0, hot_detected_at: now}, now), false);
  assert.equal(isToday({tier: 3}, now), false);
  assert.equal(dateKey(null), null);
});

test('rolling discovery windows ignore upload age and expire against the current clock', () => {
  const now = ts('2026-10-05T14:00:00Z');
  const boundary = {tier:1, age_hours:500, hot_detected_at:now-24*3600};
  assert.equal(withinHours(boundary,24,now),true);
  assert.equal(withinHours(boundary,24,now+1),false);
  assert.equal(withinHours({...boundary,age_hours:1},24,now+1),false);
  assert.equal(withinHours(boundary,72,now+1),true);
  assert.equal(withinHours({tier:2,age_hours:1},24,now),false);
  assert.equal(withinHours({tier:2,hot_detected_at:null},24,now),false);
  assert.equal(withinHours({tier:0,hot_detected_at:now},24,now),false);
});

test('today starts at Korean midnight while last 24 hours can include yesterday', () => {
  const midnight = ts('2026-10-05T15:00:00Z');
  const yesterday = {tier:1,hot_detected_at:midnight-1};
  assert.equal(isToday(yesterday,midnight),false);
  assert.equal(withinHours(yesterday,24,midnight),true);
  const future = {tier:1,hot_detected_at:midnight+60};
  assert.equal(isToday(future,midnight),false);
  assert.equal(withinHours(future,24,midnight),false);
});
