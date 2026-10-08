import test from 'node:test';
import assert from 'node:assert/strict';
import { cardBackground, cardText, cardAccent, cardOverlay } from './card-colors.mjs';
function lum(hex) { return [1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0); }
function ratio(a,b) { const x=lum(a),y=lum(b); return (Math.max(x,y)+.05)/(Math.min(x,y)+.05); }
test('partner backgrounds and overlay retain their colour',()=>{
  for(const bg of ['#183030','#F0F5FA','#ffffff','#808080','#ff8800']) {
    assert.equal(cardBackground(bg),bg);
    assert.ok(ratio(cardText(bg),bg)>=4.5);
    for(const accent of ['#a8d8ff','#f0f5fa','#183030','invalid']) assert.ok(ratio(cardAccent(accent,bg),bg)>=4.5);
  }
  assert.equal(cardOverlay('#F0F5FA',.98),'rgba(240,245,250,0.98)');
  assert.equal(cardOverlay('#183030',0),'rgba(24,48,48,0)');
});
test('invalid branding uses readable fallback',()=>{
 assert.equal(cardBackground('red'),'#061b2b');
 assert.equal(cardText('red'),'#ffffff');
 assert.equal(cardAccent('#A8D8FF','#183030'),'#A8D8FF');
});
