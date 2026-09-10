/**
 * 브라우저 덤프 스크립트 (백업용 수집 경로)
 *
 * Python 수집기가 차단당했을 때 쓰는 방법. 크롬에서 instagram.com 에 로그인한 뒤,
 * 아무 인스타그램 페이지에서 개발자도구(F12) → Console 에 이 파일 전체를 붙여넣고 Enter.
 * 끝나면 hotpost_dump.json 이 다운로드된다. 그 다음:
 *     python -m hotpost import ~/Downloads/hotpost_dump.json
 *
 * USERNAMES 에 influencer_list.txt 의 계정 이름을 넣는다.
 */
(async () => {
  const USERNAMES = ['smileful_it', 'campdog.5bok.billion', '5bok_billion_home', 'salimpickle', 'temseorap_home',
    'yiseo.home', 'issue.living', 'home_banjang_', 'reviewunnie', 'tem.doctor', 'yoonnb_home', 'home_yojung'];
  const PER_ACCOUNT = 30;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const H = { 'x-ig-app-id': '936619743392459', 'x-requested-with': 'XMLHttpRequest' };
  const kindOf = (n) => (n.media_type === 2 ? (n.product_type === 'clips' ? 'reel' : 'video') : n.media_type === 8 ? 'carousel' : 'image');
  const out = { generated_at: Math.floor(Date.now() / 1000), accounts: [] };

  for (const username of USERNAMES) {
    try {
      const info = await (await fetch(`/api/v1/users/web_profile_info/?username=${username}`, { headers: H, credentials: 'include' })).json();
      const u = info.data.user;
      const profile = { username, user_id: u.id, full_name: u.full_name, followers: u.edge_followed_by.count, following: u.edge_follow.count, media_count: u.edge_owner_to_timeline_media.count, is_private: u.is_private };
      const posts = [];
      let maxId = '';
      while (posts.length < PER_ACCOUNT) {
        const r = await (await fetch(`/api/v1/feed/user/${u.id}/?count=12${maxId ? '&max_id=' + maxId : ''}`, { headers: H, credentials: 'include' })).json();
        for (const n of r.items || []) {
          posts.push({ shortcode: n.code, taken_at: n.taken_at, kind: kindOf(n), likes: n.like_count || 0, comments: n.comment_count || 0,
            views: n.media_type === 2 ? (n.play_count ?? n.ig_play_count ?? n.view_count ?? null) : null,
            caption: n.caption ? n.caption.text : '', thumbnail_url: n.image_versions2 ? n.image_versions2.candidates[0].url : '',
            video_duration: n.video_duration || null, media_id: String(n.pk) });
        }
        if (!r.more_available || !r.next_max_id) break;
        maxId = r.next_max_id;
        await sleep(1500);
      }
      out.accounts.push({ profile, posts });
      console.log(`@${username}: ${posts.length}개`);
    } catch (e) {
      console.warn(`@${username} 실패`, e);
    }
    await sleep(2500);
  }
  const blob = new Blob([JSON.stringify(out)], { type: 'application/json' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'hotpost_dump.json'; a.click();
  console.log('완료: hotpost_dump.json 다운로드됨');
})();
