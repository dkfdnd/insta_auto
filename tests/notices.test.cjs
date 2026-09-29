const test=require('node:test');
const assert=require('node:assert/strict');
const {collection,remedy}=require('../web/notices.js');
const accounts=[{username:'active'}], now=200000;
function data(notes,overrides={}){return {collection:{state:'partial_failure',newest_post_update:now,last_run:{id:1,notes,accounts_failed:1},...overrides},schedule:{}};}
test('removed account failures remain historical, not active warnings',()=>{
 const notice=collection(data('@removed: 페이지를 사용할 수 없습니다.'),accounts,{},now);
 assert.equal(notice.tone,'info');assert.doesNotMatch(notice.title,/실패/);
});
test('active missing account includes a specific remedy and destination',()=>{
 const notice=collection(data('@active: 페이지를 사용할 수 없습니다.'),accounts,{},now);
 assert.equal(notice.tone,'warning');assert.match(notice.solution,/아이디 변경/);assert.equal(notice.actions[0].href,'accounts.html#account-list');
});
test('successful new run never reuses stale report errors',()=>{
 const notice=collection(data('',{state:'success',last_run:{id:2,notes:'',accounts_failed:0}}),accounts,{notes:['@active: 세션 만료']},now);
 assert.equal(notice.tone,'info');
});
test('stale data and missing schedule have actionable collection help',()=>{
 const value=data('',{state:'success',newest_post_update:1});value.schedule.missed_today=true;
 const notice=collection(value,accounts,{},now);
 assert.equal(notice.tone,'warning');assert.match(notice.solution,/수동 수집/);assert.equal(notice.actions[0].href,'accounts.html#help-collect');
});
test('rate limiting asks to wait while authentication asks for user login',()=>{
 assert.equal(remedy('429 rate limited').href,'accounts.html#help-rate-limit');
 assert.equal(remedy('verification_required').href,'accounts.html#help-login');
 assert.equal(remedy('session missing').href,'accounts.html#help-login');
});
test('unknown failure remains visible and running collection avoids stale errors',()=>{
 assert.equal(collection(data(''),accounts,{},now).tone,'warning');
 assert.equal(collection(data('@active: 세션 오류',{state:'running'}),accounts,{},now).tone,'info');
});
