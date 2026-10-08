/* Hot detection dates use Korean calendar days, independent of browser timezone. */
(function (root) {
  'use strict';
  const dateKey = seconds => seconds == null ? null : new Date(seconds * 1000 + 9 * 3600000).toISOString().slice(0, 10);
  const hasDetection = (post, now) => post.tier >= 1 &&
    Number.isFinite(post.hot_detected_at) && post.hot_detected_at >= 0 && post.hot_detected_at <= now;
  const isToday = (post, now = Date.now() / 1000) => hasDetection(post, now) &&
    dateKey(post.hot_detected_at) === dateKey(now);
  const withinHours = (post, hours, now = Date.now() / 1000) => hasDetection(post, now) &&
    Number.isFinite(hours) && hours > 0 && post.hot_detected_at >= now - hours * 3600;
  const consumed = (post, now = Date.now() / 1000) => post.tier >= 1 &&
    (post.hot_detected_at == null || dateKey(post.hot_detected_at) < dateKey(now));
  const compare = (a, b, key, now = Date.now() / 1000) =>
    Number(isToday(b, now)) - Number(isToday(a, now)) || key(b) - key(a) || b.taken_at - a.taken_at;
  const api = {dateKey, isToday, withinHours, consumed, compare};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.HotpostDetection = api;
})(globalThis);
