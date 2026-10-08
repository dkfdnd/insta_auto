/* Update the dashboard snapshot without navigating away from an open player. */
(function (root) {
  'use strict';

  function create({initial, onReport, fetchReport}) {
    const signature = report => [report.generated_at, report.criteria?.version, report.posts?.length].join(':');
    let current = signature(initial);
    let inFlight = null;

    function refresh() {
      if (inFlight) return inFlight;
      inFlight = (async () => {
        const report = await fetchReport();
        if (!Array.isArray(report?.posts) || !report.criteria?.values || !report.settings || !report.summary) {
          throw new Error('수집 결과를 읽지 못했습니다.');
        }
        const next = signature(report);
        if (next === current) return false;
        onReport(report);
        current = next;
        return true;
      })().finally(() => { inFlight = null; });
      return inFlight;
    }

    return {refresh};
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = {create};
  else root.HotpostReportRefresh = {create};
})(globalThis);
