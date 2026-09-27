const {test} = require('node:test');
const assert = require('node:assert/strict');
const {dateKey, isToday} = require('../web/hot-detection.js');
const ts = iso => Date.parse(iso) / 1000;
test('Korean midnight separates today from yesterday', () => {
  const midnight = ts('2026-09-26T15:00:00Z');
  assert.equal(dateKey(midnight), '2026-09-27');
  assert.equal(dateKey(midnight - 1), '2026-09-26');
  assert.equal(isToday({tier: 1, hot_detected_at: midnight}, midnight + 1), true);
  assert.equal(isToday({tier: 3, hot_detected_at: midnight - 1}, midnight + 1), false);
});
test('old publication may be newly hot; normal and undated posts are excluded', () => {
  const now = ts('2026-09-27T01:00:00Z');
  assert.equal(isToday({tier: 1, age_hours: 500, hot_detected_at: now}, now), true);
  assert.equal(isToday({tier: 0, hot_detected_at: now}, now), false);
  assert.equal(isToday({tier: 3}, now), false);
  assert.equal(dateKey(null), null);
});
