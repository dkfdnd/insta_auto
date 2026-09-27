/* Hot detection dates use Korean calendar days, independent of browser timezone. */
(function (root) {
  'use strict';
  const dateKey = seconds => seconds == null ? null : new Date(seconds * 1000 + 9 * 3600000).toISOString().slice(0, 10);
  const isToday = (post, now = Date.now() / 1000) => post.tier >= 1 &&
    post.hot_detected_at != null && dateKey(post.hot_detected_at) === dateKey(now);
  const api = {dateKey, isToday};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.HotpostDetection = api;
})(globalThis);
