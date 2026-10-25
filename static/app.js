'use strict';
const TG = window.Telegram && Telegram.WebApp, DEV = new URLSearchParams(location.search).get('dev');
if (TG) { try { TG.ready(); TG.expand(); TG.setHeaderColor('#120d22'); TG.setBackgroundColor('#120d22'); } catch (e) {} }
const $ = s => document.querySelector(s), fmt = n => Math.round(n).toLocaleString('ru-RU'), CN = '<i class="cn"></i>', sleep = ms => new Promise(r => setTimeout(r, ms));
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
let IT, TR, K, CS = {}, S;
const U = { tab: 'cases', cs: null, sel: new Set(), tg: null, flt: -1, busy: 0, ang: 0, reel: 0, cart: {}, f: { min: 0, max: 0, q: '' }, pane: 'inv', ad: 'promo' };
const PR = Object.assign({ fast: 0, xs: [2, 4, 8], ps: [30, 50, 75], mute: 0 }, (() => { try { return JSON.parse(localStorage.getItem('bvp') || '{}'); } catch (e) { return {}; } })());
const savePR = () => { try { localStorage.setItem('bvp', JSON.stringify(PR)); } catch (e) {} };

async function api(p, body) {
  const h = { 'Content-Type': 'application/json', 'X-Init-Data': TG ? TG.initData : '' };
  if (DEV) h['X-Dev-User'] = DEV;
  let r, j;
  try { r = await fetch('/api/' + p, { method: body ? 'POST' : 'GET', headers: h, body: body ? JSON.stringify(body) : undefined }); j = await r.json(); }
  catch (e) { throw new Error('Нет связи с сервером'); }
  if (!r.ok) throw new Error(j.error || 'Ошибка');
  return j;
}
const run = async f => { try { await f(); } catch (e) { toast(e.message || 'Ошибка'); } };

/* ---------- звуки и анимация ---------- */
let AC;
function tone(f, d = .08, ty = 'sine', v = .1, at = 0) {
  if (PR.mute) return;
  try {
    AC = AC || new (window.AudioContext || window.webkitAudioContext)(); if (AC.state === 'suspended') AC.resume();
    const o = AC.createOscillator(), g = AC.createGain(), t = AC.currentTime + at;
    o.type = ty; o.frequency.setValueAtTime(f, t); g.gain.setValueAtTime(v, t); g.gain.exponentialRampToValueAtTime(.001, t + d);
    o.connect(g); g.connect(AC.destination); o.start(t); o.stop(t + d);
  } catch (e) {}
}
const SFX = {
  tick: () => tone(850 + Math.random() * 90, .04, 'triangle', .07), click: () => tone(520, .05, 'triangle', .08),
  coin: () => { tone(1320, .09, 'square', .04); tone(1760, .16, 'square', .04, .08); },
  lose: () => { tone(220, .25, 'sawtooth', .07); tone(140, .4, 'sawtooth', .07, .18); },
  win: ti => { for (let i = 0; i < 3 + ti; i++) tone(523 * Math.pow(1.26, i), .24, 'triangle', .1, i * .09); }
};
const ease = t => 1 - Math.pow(1 - t, 4);
function anim(ms, fn, done) { const t0 = performance.now(); (function f(t) { const x = Math.min(1, (t - t0) / ms); fn(ease(x)); x < 1 ? requestAnimationFrame(f) : done && done(); })(t0); }
let tt; function toast(s) { const e = $('#toast'); e.textContent = s; e.classList.add('on'); clearTimeout(tt); tt = setTimeout(() => e.classList.remove('on'), 2600); }

/* ---------- помощники ---------- */
const setS = s => { S = s; S.at = Date.now(); S.off = s.cfg.srv - Math.floor(Date.now() / 1000); upd(); };
const nowS = () => Math.floor(Date.now() / 1000) + (S ? S.off : 0);
const dur = s => { s = Math.max(0, Math.floor(s)); return s >= 3600 ? `${Math.floor(s / 3600)} ч ${Math.floor(s % 3600 / 60)} мин` : `${Math.floor(s / 60)} мин ${s % 60} с`; };
const fd = t => new Date(t * 1000).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
const buyp = i => Math.floor((i.p * (100 + S.cfg.mk) + 50) / 100), pc = x => (x * 100).toFixed(x < .01 ? 2 : 1) + '%';
const pick = r => { let x = Math.random(), a = 0; for (const o of r) { a += o[1]; if (x < a) return o[0]; } return r[r.length - 1][0]; };
const card = (it, x = '', c = '', a = '', pr = it.p) => `<div class="it ${c}" ${a} style="--rc:${TR[it.t][1]}"><img src="/static/b/${it.id}.webp" alt="" loading="lazy"><div class="n">${esc(it.n)}</div><div class="r">${TR[it.t][0]}</div><div class="p">${CN}${fmt(pr)}</div>${x}</div>`;
const ic = { case: '📦', up: '⚡', buy: '🛒', sell: '💰', bonus: '🎁', dep: '⭐', wd: '📤' };
const upd = () => { $('#bal').textContent = S ? fmt(S.bal) : '0'; };
const shut = () => { $('#ov').hidden = true; };
function modal(it, title, btns, msg, cls = '') {
  const o = $('#ov'); o.hidden = false;
  o.innerHTML = `<div class="md ${cls}" style="--rc:${it ? TR[it.t][1] : '#ff5a6e'}"><h3>${title}</h3>${it ? `<div style="text-align:center"><img src="/static/b/${it.id}.webp" alt=""><div style="font-size:20px;font-weight:800">${esc(it.n)}</div><div class="mu">${TR[it.t][0]} · ${CN}${fmt(it.p)}</div></div>` : ''}${msg ? `<p class="mu">${msg}</p>` : ''}<div class="row" style="flex-wrap:wrap">${btns}</div></div>`;
}
const chips = () => `<div class="chips">${['Все', ...TR.map(t => t[0])].map((t, i) => `<button data-a="flt" data-v="${i - 1}" class="${U.flt === i - 1 ? 'on' : ''}">${t}</button>`).join('')}</div>`;
function tabs() {
  const t = [['cases', 'Кейсы'], ['up', 'Апгрейд'], ['prof', 'Профиль'], ['bon', 'Бонусы']]; if (S && S.me.role) t.push(['adm', 'Админ']);
  $('#nav').innerHTML = t.map(x => `<button data-a="tab" data-v="${x[0]}" class="${U.tab === x[0] ? 'on' : ''}">${x[1]}</button>`).join('');
}

/* ---------- кейсы ---------- */
function caseCard(c) {
  const fr = S.free[c.id], cd = S.cd[c.id], soon = c.k === 'soon', free = c.k === 'free' || c.k === 'sub'; let bd = '';
  if (soon) bd = 'Скоро'; else if (free) bd = cd ? '⏳ ' + dur(cd - nowS()) : 'Бесплатно'; else if (fr) bd = '🎁 ×' + fr;
  const top = IT[c.r[0][0]], low = IT[c.r[c.r.length - 1][0]];
  return `<div class="case ${soon ? 'lock' : ''}" ${soon ? '' : `data-a="case" data-v="${c.id}"`} style="--rc:${c.col}">${bd ? `<div class="bd">${bd}</div>` : ''}<img class="hk" src="/static/b/${top.id}.webp" alt=""><img src="/static/${c.img}" alt=""><div class="t">${esc(c.n)}</div><div class="pr">${c.p ? CN + fmt(c.p) : 'Бесплатно'}</div><div class="mu">от ${fmt(low.p)} до ${fmt(top.p)}</div></div>`;
}
const vCases = () => K.cats.map(c => `<h2 class="cath">${c.title}</h2><div class="catd">${c.desc}</div><div class="cases">${c.cases.map(caseCard).join('')}</div>`).join('');
function vCase() {
  const c = CS[U.cs], fr = S.free[c.id], cd = S.cd[c.id], free = c.k === 'free' || c.k === 'sub';
  const label = free ? (cd ? 'Доступно через ' + dur(cd - nowS()) : 'Открыть бесплатно') : fr ? `Открыть бесплатно (×${fr})` : `Открыть за ${CN}${fmt(c.p)}`;
  return `<div class="cv" style="--rc:${c.col}"><div class="top"><button class="b g s" data-a="back">← Назад</button><img src="/static/${c.img}" alt=""><div><h2 style="margin:0">${esc(c.n)}</h2><div class="mu">★ — тематические брейнроты, остальные случайные</div></div></div>
<div class="reel"><div class="mk"></div><div class="strip" id="st">${Array.from({ length: 12 }, () => card(IT[pick(c.r)])).join('')}</div></div>
<div class="ctl"><button class="b" data-a="open" ${U.reel || (free && cd) ? 'disabled' : ''} style="font-size:17px;padding:14px 26px">${label}</button><button class="b g fast ${PR.fast ? 'on' : ''}" data-a="fast" title="Быстрая прокрутка">⚡</button></div>
<h3>Что внутри</h3><div class="grid">${c.r.map(o => card(IT[o[0]], `<div class="ch">${pc(o[1])}</div>${o[2] ? '<div class="th">★</div>' : ''}`)).join('')}</div></div>`;
}
async function openCase() {
  const c = CS[U.cs]; if (U.reel) return; U.reel = 1; let j;
  try { j = await api('open', { case: c.id }); } catch (e) { U.reel = 0; return toast(e.message); }
  setS(j.state); const win = IT[j.win], N = 58, W = 46, list = Array.from({ length: N }, (_, i) => i === W ? win : IT[pick(c.r)]);
  const st = $('#st'); $('[data-a=open]').disabled = 1; st.innerHTML = list.map(i => card(i)).join('');
  const rw = st.parentNode.clientWidth, fin = W * 128 + 60 - rw / 2 + (Math.random() * 70 - 35); let last = -1; SFX.click();
  anim(PR.fast ? 1100 : 6000, e => { const x = e * fin; st.style.transform = `translateX(${-x}px)`; const q = Math.floor((x + rw / 2) / 128); if (q !== last) { last = q; SFX.tick(); } },
    () => { U.reel = 0; SFX.win(win.t); modal(win, 'Выпало!', `<button class="b g" data-a="sell1" data-v="${j.uid}">Продать ${CN}${fmt(win.p)}</button><button class="b" data-a="again">Ещё раз</button>`); });
}

/* ---------- апгрейд: инвентарь + рулетка + магазин ---------- */
const invOf = u => S.inv.find(o => o.u === u);
const stake = () => [...U.sel].reduce((a, u) => { const o = invOf(u); return a + (o ? IT[o.i].p : 0); }, 0);
const chance = () => { const s = stake(); return U.tg == null || !s ? 0 : Math.max(.5, Math.min(S.cfg.edge, s / IT[U.tg].p * S.cfg.edge)); };
const near = v => IT.reduce((a, b) => Math.abs(b.p - v) < Math.abs(a.p - v) ? b : a);
const cartN = () => Object.values(U.cart).reduce((a, b) => a + b, 0), cartTot = () => Object.keys(U.cart).reduce((a, k) => a + buyp(IT[k]) * U.cart[k], 0);
function vUp() {
  const X = PR.xs.map(m => `<button data-a="mult" data-v="${m}">x${m}</button>`).join(''), P = PR.ps.map(p => `<button data-a="pct" data-v="${p}">${p}%</button>`).join('');
  return `<h2>Апгрейд</h2><div class="up" data-pane="${U.pane}"><div class="seg"><button data-a="pane" data-v="inv" class="${U.pane === 'inv' ? 'on' : ''}">🎒 Инвентарь</button><button data-a="pane" data-v="shop" class="${U.pane === 'shop' ? 'on' : ''}">🛒 Магазин</button></div>
<div class="pn" id="pinv"><div class="top" style="margin:0 0 8px;justify-content:space-between"><h3 style="margin:0">Инвентарь <span class="mu" id="invs"></span></h3><span><button class="sm" data-a="selall">Все</button> <button class="sm" data-a="selno">Сброс</button></span></div><div class="scr"><div class="grid" id="invg"></div></div></div>
<div class="pn w"><div id="wd"></div><div class="chips">${X}<input class="ni" id="cx" type="number" step="0.1" min="1.1" placeholder="x свой" inputmode="decimal"></div><div class="chips">${P}<input class="ni" id="cp" type="number" min="1" max="90" placeholder="% свой" inputmode="decimal"></div>
<div class="ctl"><button class="b" data-a="spin" style="flex:1;font-size:17px">Апгрейд</button><button class="b g fast ${PR.fast ? 'on' : ''}" data-a="fast" title="Быстрая прокрутка">⚡</button><button class="b g" data-a="cfg" title="Настройки x и %">⚙</button></div></div>
<div class="pn" id="pshop"><h3>Магазин <span class="mu" id="shn"></span></h3><div class="flt"><input id="fmin" type="number" placeholder="цена от" inputmode="numeric"><input id="fmax" type="number" placeholder="цена до" inputmode="numeric"><input id="fq" type="search" placeholder="Поиск"></div><div class="mu" style="margin-bottom:8px">Цена на ${S.cfg.mk}% выше стоимости. Нажми на брейнрота — он попадёт в корзину, 🎯 — выбрать целью апгрейда.</div><div class="scr" style="max-height:62vh"><div class="grid" id="shg"></div></div></div></div>`;
}
function fillInv() {
  const inv = S.inv.slice().sort((a, b) => IT[b.i].p - IT[a.i].p);
  $('#invg').innerHTML = inv.length ? inv.map(o => card(IT[o.i], '', U.sel.has(o.u) ? 'sel' : '', `data-a="pin" data-v="${o.u}"`)).join('') : '<div class="emp" style="grid-column:1/-1">Пусто. Открой кейс или купи брейнрота в магазине.</div>';
  $('#invs').textContent = U.sel.size ? `· выбрано ${U.sel.size} на ${fmt(stake())}` : `· ${inv.length} шт.`;
}
function fillWheel() {
  const s = stake(), ch = chance(), T = U.tg == null ? null : IT[U.tg], C = 2 * Math.PI * 84;
  $('#wd').innerHTML = `<div class="wc"><svg class="wh" viewBox="0 0 200 200"><circle cx="100" cy="100" r="84" fill="none" stroke="#3a2a63" stroke-width="14"/><circle cx="100" cy="100" r="84" fill="none" stroke="#3be08a" stroke-width="14" stroke-dasharray="${C * ch / 100} ${C}" transform="rotate(-90 100 100)" style="filter:drop-shadow(0 0 5px #3be08a)"/><circle cx="100" cy="100" r="68" fill="none" stroke="#ffffff1f" stroke-width="5" stroke-dasharray="1.2 6.1"/><g id="nd" style="transform:rotate(${U.ang}deg);transform-origin:100px 100px"><path d="M100 26L91 4H109Z" fill="#fff"/></g></svg><div class="wi">${T ? `<img src="/static/b/${T.id}.webp" alt=""><b>${ch.toFixed(ch < 10 ? 1 : 0)}%</b>` : '<div class="mu">Выбери цель</div>'}</div></div><div class="mu" style="text-align:center">Ставка: ${CN}${fmt(s)}${T ? ` → ${esc(T.n)} ${CN}${fmt(T.p)}` : ''}</div>`;
}
function fillShop() {
  const f = U.f, q = f.q.toLowerCase(), L = IT.filter(i => buyp(i) >= (f.min || 0) && buyp(i) <= (f.max || 1e12) && (!q || i.n.toLowerCase().includes(q))).sort((a, b) => a.p - b.p);
  $('#shg').innerHTML = L.length ? L.map(i => card(i, `<button class="tgb" data-a="tg" data-v="${i.id}">🎯</button>${U.cart[i.id] ? `<div class="qb">×${U.cart[i.id]}</div>` : ''}`, U.tg === i.id ? 'tg' : '', `data-a="cadd" data-v="${i.id}"`, buyp(i))).join('') : '<div class="emp" style="grid-column:1/-1">Ничего не найдено</div>';
  $('#shn').textContent = '· ' + L.length;
}
function fillBar() {
  const b = $('#bbar'); if (U.tab !== 'up') { b.hidden = true; return; }
  const n = cartN(), tot = cartTot(), s = stake(), T = U.tg == null ? null : IT[U.tg];
  if (n) { b.hidden = false; b.innerHTML = `<div class="s"><b>🛒 ${n} шт. · ${CN}${fmt(tot)}</b>Корзина магазина</div><div class="bb"><button class="b g" data-a="cart">Корзина</button><button class="b" data-a="cbuy" ${tot > S.bal ? 'disabled' : ''}>Купить</button></div>`; }
  else if (s && T && T.p > s) { b.hidden = false; b.innerHTML = `<div class="s"><b>${CN}${fmt(s)} → ${esc(T.n)}</b>Шанс ${chance().toFixed(1)}%</div><div class="bb"><button class="b" data-a="spin" ${U.busy ? 'disabled' : ''}>Апгрейд</button></div>`; }
  else b.hidden = true;
}
function fillUp() { $('#fmin').value = U.f.min || ''; $('#fmax').value = U.f.max || ''; $('#fq').value = U.f.q; fillInv(); fillWheel(); fillShop(); fillBar(); }
function openCart() {
  const ids = Object.keys(U.cart).filter(k => U.cart[k] > 0); if (!ids.length) { shut(); fillBar(); return; }
  const rows = ids.map(k => `<div class="cl"><img src="/static/b/${k}.webp" alt=""><div class="n">${esc(IT[k].n)}<div class="mu">${CN}${fmt(buyp(IT[k]))}</div></div><div class="q"><button data-a="cdec" data-v="${k}">−</button><b>${U.cart[k]}</b><button data-a="cadd" data-v="${k}">+</button></div><button class="x" data-a="cdel" data-v="${k}">✕</button></div>`).join('');
  const o = $('#ov'); o.hidden = false;
  o.innerHTML = `<div class="md wide"><h3>Корзина (${cartN()})</h3>${rows}<div class="row"><button class="b g" data-a="cclr">Очистить</button><button class="b" data-a="cbuy" ${cartTot() > S.bal ? 'disabled' : ''}>Купить за ${CN}${fmt(cartTot())}</button></div><p class="mu">Баланс: ${CN}${fmt(S.bal)}</p></div>`;
}
async function spin() {
  if (U.busy) return; const s = stake(), T = U.tg == null ? null : IT[U.tg];
  if (!s || !T) return toast('Выбери брейнрота и цель'); if (T.p <= s) return toast('Цель должна быть дороже ставки');
  U.busy = 1; let j; try { j = await api('upgrade', { uids: [...U.sel], target: T.id }); } catch (e) { U.busy = 0; return toast(e.message); }
  setS(j.state); const ch = j.chance, win = j.win, a = ch * 3.6, pos = win ? a * (.08 + Math.random() * .84) : a + (360 - a) * (.04 + Math.random() * .92);
  const st = U.ang, end = Math.ceil(st / 360) * 360 + (PR.fast ? 720 : 1800) + pos, nd = document.getElementById('nd'); let last = -1; SFX.click();
  anim(PR.fast ? 1300 : 5200, e => { const v = st + (end - st) * e; U.ang = v; nd.style.transform = `rotate(${v}deg)`; const q = Math.floor(v / 9); if (q !== last) { last = q; SFX.tick(); } }, () => {
    U.sel.clear(); U.busy = 0; U.tg = null;
    if (win) { SFX.win(T.t + 2); modal(T, 'Апгрейд удался!', '<button class="b" data-a="shut">Забрать</button>'); }
    else { SFX.lose(); modal(null, 'Не повезло', '<button class="b" data-a="shut" style="flex:0 0 100%">Ок</button>', 'Ставка сгорела. Попробуй ещё раз.'); }
    if (U.tab === 'up') { fillInv(); fillWheel(); fillShop(); fillBar(); }
  });
}

/* ---------- профиль, вывод, пополнение ---------- */
function vProf() {
  const m = S.me, tot = S.inv.reduce((a, o) => a + IT[o.i].p, 0), L = S.inv.filter(o => U.flt < 0 || IT[o.i].t === U.flt).sort((a, b) => IT[b.i].p - IT[a.i].p), stl = { pending: ['⏳ ждёт', 'wt'], done: ['✅ выдан', 'ok'], rejected: ['❌ отклонён', 'bad'] };
  return `<h2>Профиль</h2><div class="pf">${m.photo ? `<img class="avp" src="${esc(m.photo)}" alt="">` : `<div class="av">${esc((m.name[0] || 'И').toUpperCase())}</div>`}<div><div style="font-size:20px;font-weight:800">${esc(m.name)}</div><div class="mu">${m.un ? '@' + esc(m.un) + ' · ' : ''}ID ${m.id}${m.rname ? ' · ' + esc(m.rname) : ''}</div></div><button class="b" data-a="dep" style="margin-left:auto">⭐ Пополнить</button></div>
<div class="stats"><div class="stat"><span class="mu">Баланс</span><b>${CN}${fmt(S.bal)}</b></div><div class="stat"><span class="mu">Инвентарь</span><b>${CN}${fmt(tot)}</b></div><div class="stat"><span class="mu">Кейсов открыто</span><b>${S.st.c}</b></div><div class="stat"><span class="mu">Апгрейды (успех/всего)</span><b>${S.st.w}/${S.st.u}</b></div><div class="stat"><span class="mu">Лучший дроп</span><b style="font-size:15px">${esc(S.st.bn) || '—'}</b></div></div>
${S.wd.length ? `<h3>Заявки на вывод</h3>${S.wd.map(w => `<div class="rowc"><span>#${w.id} · ${esc(IT[w.item].n)} → <b>${esc(w.nick)}</b><br><span class="mu">${fd(w.t)}${w.note ? ' · ' + esc(w.note) : ''}</span></span><span class="tag ${stl[w.st][1]}">${stl[w.st][0]}</span></div>`).join('')}<div style="height:18px"></div>` : ''}
<div class="top" style="justify-content:space-between"><h3 style="margin:0">Мои брейнроты (${S.inv.length})</h3><button class="b g s" data-a="sellall" ${L.length ? '' : 'disabled'}>Продать показанное</button></div>${chips()}
${L.length ? `<div class="grid">${L.map(o => { const it = IT[o.i]; return card(it, `<div class="bt"><button class="b g s" data-a="sell" data-v="${o.u}">Продать</button><button class="b s" data-a="wd" data-v="${o.u}" ${it.p < S.cfg.minwd ? 'disabled title="Вывод от ' + S.cfg.minwd + '"' : ''}>Вывести</button></div>`); }).join('')}</div><div class="mu" style="margin-top:8px">Вывод доступен для брейнротов от ${fmt(S.cfg.minwd)} монет.</div>` : '<div class="emp">Здесь пусто.</div>'}
<h3 style="margin-top:24px">История</h3>${S.hist.length ? S.hist.map(e => `<div class="hs"><span>${ic[e.k] || ''} ${esc(e.m)}<br><span class="mu">${fd(e.t)}</span></span><b class="${e.d >= 0 ? 'pos' : 'neg'}">${e.d > 0 ? '+' : ''}${fmt(e.d)}</b></div>`).join('') : '<div class="emp">История пока пуста.</div>'}`;
}
function openWd(u) {
  const o = invOf(u); if (!o) return;
  modal(IT[o.i], 'Вывод брейнрота', `<input id="wnick" placeholder="Твой ник в Roblox" maxlength="20" autocomplete="off" autocapitalize="off"><button class="b" data-a="wdsend" data-v="${u}" style="width:100%;margin-top:10px">Отправить заявку</button>`,
    `Укажи свой ник в Roblox (3–20 символов). Заявку проверит владелец и выдаст брейнрота в игре — статус смотри в профиле. Твой Telegram${S.me.un ? ': @' + esc(S.me.un) : ' без username — открой настройки Telegram и задай его'}. Вывод от ${fmt(S.cfg.minwd)} монет.`, 'wide');
}
function openDep() {
  const r = S.cfg.rate, b = S.depb;
  modal(null, 'Пополнение ⭐', `<div class="packs" style="width:100%">${S.cfg.packs.map(p => `<button class="pk" data-a="pay" data-v="${p}"><b>${p} ⭐</b><span>${CN}${fmt(Math.floor(p * r * (1 + b / 100)))}</span></button>`).join('')}</div>`,
    `1 ⭐ = ${r} монет.${b ? ` Бонус к пополнению: <b>+${b}%</b> (применится один раз).` : ''} Промокод вводится во вкладке «Бонусы».`, 'wide');
}
async function pay(stars) {
  const j = await api('deposit', { stars }); if (!TG || !TG.openInvoice) return toast('Открой игру внутри Telegram, чтобы оплатить');
  shut(); TG.openInvoice(j.link, async st => {
    if (st === 'paid') { toast('Оплата прошла, зачисляем…'); const was = S.bal; for (let k = 0; k < 8; k++) { await sleep(1200); const n = await api('state'); setS(n); if (n.bal !== was) break; } render(); toast('Монеты зачислены ✨'); }
    else if (st === 'failed') toast('Оплата не прошла');
  });
}

/* ---------- бонусы и промокод ---------- */
function bleft() { return Math.max(0, S.cfg.bleft - (Date.now() - S.at) / 1000); }
function vBon() {
  const l = bleft(), c = S.cfg;
  return `<h2>Бонусы</h2><div class="warn">⚠️ Скоро все бесплатное уберём — это настоящий Telegram-бот. Забирай бонусы, пока они есть.</div>
<h3>Промокод</h3><div class="pcode"><input id="pcode" placeholder="Введи промокод" maxlength="24" autocomplete="off" autocapitalize="characters"><button class="b" data-a="promo">Применить</button></div>${S.depb ? `<div class="mu" style="margin-top:8px">Активен бонус к пополнению: <b>+${S.depb}%</b></div>` : ''}
<h3 style="margin-top:22px">Бонусы</h3><div class="cases">${c.bon ? `<div class="pn bc"><div style="font-size:34px">🎁</div><h3>Бонус монет</h3><div class="mu">+${fmt(c.bamt)} монет, раз в ${Math.round((c.bcd || 600) / 60)} мин</div><button class="b" id="bbtn" data-a="bonus" ${l > 0 ? 'disabled' : ''}>${l > 0 ? 'Через ' + dur(l) : 'Забрать +' + fmt(c.bamt)}</button></div>` : ''}${['Ежедневная награда', 'Задания', 'Друзья'].map(t => `<div class="pn bc dim"><div style="font-size:34px">🔒</div><h3>${t}</h3><div class="mu">Скоро</div></div>`).join('')}</div>`;
}

/* ---------- админ-меню (владелец и роли) ---------- */
const SETL = { start_balance: 'Стартовый баланс', bonus_on: 'Бесплатный бонус (1/0)', bonus_amount: 'Размер бонуса', bonus_cd: 'Кулдаун бонуса, сек', free_on: 'Бесплатные кейсы (1/0)', rate: 'Монет за 1 ⭐', min_withdraw: 'Мин. вывод (монет)', markup: 'Наценка магазина, %' };
const vAdm = () => {
  const own = S.me.role === 4, t = [['promo', '🎟 Промокоды'], ...(own ? [['staff', '👥 Персонал'], ['wd', '📦 Выводы'], ['set', '⚙️ Настройки'], ['give', '💰 Выдать']] : [])];
  return `<h2>Админ-меню</h2><div class="chips">${t.map(x => `<button data-a="atab" data-v="${x[0]}" class="${U.ad === x[0] ? 'on' : ''}">${x[1]}</button>`).join('')}</div><div id="adc" class="pn"></div>`;
};
const kindL = p => p.kind === 'deposit' ? `бонус к депозиту +${p.value}%` : p.kind === 'coins' ? `${fmt(p.value)} монет` : `кейс «${esc(p.case)}» ×${p.qty}`;
async function loadAd() {
  const el = $('#adc'), own = S.me.role === 4; el.innerHTML = '<div class="emp">Загрузка…</div>';
  try {
    if (U.ad === 'promo') {
      const [pl, ov] = await Promise.all([api('admin/promos'), own ? api('admin/overview') : null]), L = S.lim, stl = { ok: ['активен', 'ok'], off: ['выключен', 'bad'], expired: ['истёк', 'bad'], full: ['лимит', 'bad'] };
      const co = K.cats.flatMap(c => c.cases).filter(c => c.k === 'paid').sort((a, b) => a.p - b.p).map(c => `<option value="${c.id}">${esc(c.n)} — ${fmt(c.p)}</option>`).join('');
      el.innerHTML = (ov ? `<div class="stats"><div class="stat"><span class="mu">Игроков</span><b>${ov.users}</b></div><div class="stat"><span class="mu">Получено ⭐</span><b>${fmt(ov.stars)}</b></div><div class="stat"><span class="mu">Платежей</span><b>${ov.pay}</b></div><div class="stat"><span class="mu">Заявок на вывод</span><b>${ov.wd}</b></div></div>` : '')
        + (L ? `<div class="lim">Твой уровень: <b>${esc(S.me.rname)}</b> · бонус к депозиту до ${L.dep}% · до ${L.acts} активаций · срок до ${L.hours} ч · монеты до ${L.coins} · кейсы до ${fmt(L.case)}</div>` : '')
        + `<h3>Создать промокод</h3><div class="fm"><div><label>Тип</label><select id="pk"><option value="deposit">Бонус к депозиту</option><option value="coins">Монеты</option><option value="case">Бесплатные кейсы</option></select></div><div id="pvw"><label id="pvl">Бонус, %</label><input id="pv" type="number" min="1" placeholder="${L ? L.dep : 50}"></div><div id="pcw" style="display:none"><label>Кейс</label><select id="pc">${co}</select></div><div id="pqw" style="display:none"><label>Открытий кейса</label><input id="pq" type="number" min="1" value="1"></div><div><label>Код (пусто = случайный)</label><input id="pcd" maxlength="24" placeholder="напр. TUKE50"></div>${own ? '<div><label>Макс. активаций (0 = ∞)</label><input id="pa" type="number" min="0" value="0"></div><div><label>Срок, часов (0 = ∞)</label><input id="ph" type="number" min="0" value="0"></div>' : ''}</div><button class="b" data-a="pcreate">Создать</button>`
        + `<h3 style="margin-top:20px">${own ? 'Все промокоды' : 'Мои промокоды'}</h3>` + (pl.list.length ? pl.list.map(p => `<div class="rowc"><div><b>${esc(p.code)}</b> <span class="tag ${stl[p.st][1]}">${stl[p.st][0]}</span><br><span class="mu">${kindL(p)} · ${p.used}/${p.max || '∞'} акт. · ${p.exp ? 'до ' + fd(p.exp) : 'без срока'}${own ? ' · @' + esc(p.by) : ''}</span></div><div class="act"><button class="b g s" data-a="puses" data-v="${esc(p.code)}">Кто</button><button class="b s" data-a="ptoggle" data-v="${esc(p.code)}" data-on="${p.st === 'off' ? 1 : 0}">${p.st === 'off' ? 'Вкл' : 'Выкл'}</button></div></div>`).join('') : '<div class="emp">Пока пусто</div>');
    } else if (U.ad === 'staff') {
      const j = await api('admin/staff');
      el.innerHTML = `<h3>Выдать / изменить права</h3><div class="fm"><div><label>Telegram username</label><input id="ru" placeholder="@username" autocapitalize="off"></div><div><label>Уровень</label><select id="rl"><option value="1">1 · Блогер — +5% к депозиту, 10 активаций</option><option value="2">2 · Помощник — +10%, 50 активаций</option><option value="3">3 · Партнёр — +25%, 100 активаций</option><option value="0">Снять права</option></select></div></div><button class="b" data-a="role">Сохранить</button><h3 style="margin-top:20px">Персонал и активность</h3>`
        + (j.list.length ? j.list.map(s => `<div class="rowc" style="align-items:flex-start"><div><b>@${esc(s.un)}</b> <span class="tag">${s.role} · ${esc(s.rname)}</span>${s.seen ? '' : ' <span class="tag wt">ещё не заходил</span>'}<br><span class="mu">промо: ${s.promos} · активаций: ${s.acts} · людей: ${s.users} · последняя: ${s.last ? fd(s.last) : '—'}</span>${s.recent.length ? `<div class="mu" style="margin-top:4px">${s.recent.map(r => `${esc(r.code)} ← ${esc(r.u)} (${fd(r.t)})`).join('<br>')}</div>` : ''}</div></div>`).join('') : '<div class="emp">Персонала пока нет</div>');
    } else if (U.ad === 'wd') {
      const j = await api('admin/wd'), stl = { pending: ['⏳ ждёт', 'wt'], done: ['✅ выдан', 'ok'], rejected: ['❌ отклонён', 'bad'] };
      el.innerHTML = j.list.length ? j.list.map(w => `<div class="rowc"><div><b>#${w.id}</b> ${esc(IT[w.item].n)} <span class="mu">(${fmt(w.price)} монет)</span><br><span class="mu">Roblox: <b style="color:var(--tx)">${esc(w.nick)}</b> · Telegram: ${w.tg ? '@' + esc(w.tg) : w.uid} · ${fd(w.t)}</span></div><div class="act">${w.st === 'pending' ? `<button class="b s" data-a="wdok" data-v="${w.id}">Выдан ✅</button><button class="b g s" data-a="wdno" data-v="${w.id}">Отклонить</button>` : `<span class="tag ${stl[w.st][1]}">${stl[w.st][0]}</span>`}</div></div>`).join('') : '<div class="emp">Заявок нет</div>';
    } else if (U.ad === 'set') {
      const j = await api('admin/settings');
      el.innerHTML = `<div class="fm">${Object.keys(SETL).map(k => `<div><label>${SETL[k]}</label><input data-set="${k}" type="number" min="0" value="${j.v[k]}"></div>`).join('')}</div><button class="b" data-a="setsave">Сохранить</button>`;
    } else if (U.ad === 'give') {
      el.innerHTML = `<h3>Выдать монеты игроку</h3><div class="fm"><div><label>Telegram username</label><input id="gu" placeholder="@username" autocapitalize="off"></div><div><label>Монет</label><input id="ga" type="number" value="100"></div></div><button class="b" data-a="give">Выдать</button>`;
    }
  } catch (e) { el.innerHTML = `<div class="emp">${esc(e.message)}</div>`; }
}

/* ---------- отрисовка и события ---------- */
function render() {
  tabs(); upd(); const m = $('#m');
  m.innerHTML = U.tab === 'cases' ? (U.cs == null ? vCases() : vCase()) : U.tab === 'up' ? vUp() : U.tab === 'prof' ? vProf() : U.tab === 'bon' ? vBon() : vAdm();
  if (U.tab === 'up') fillUp(); else fillBar(); if (U.tab === 'adm') loadAd();
}
async function refresh() { setS(await api('state')); }
function act(a, v, b) {
  const n = +v;
  run(async () => {
    switch (a) {
      case 'tab': if (U.reel || U.busy) return; U.tab = v; U.cs = null; U.flt = -1; U.sel.clear(); SFX.click(); return render();
      case 'case': U.cs = n; SFX.click(); return render();
      case 'back': if (U.reel) return; U.cs = null; return render();
      case 'open': return openCase();
      case 'fast': PR.fast ^= 1; savePR(); document.querySelectorAll('.fast').forEach(x => x.classList.toggle('on', !!PR.fast)); return;
      case 'flt': U.flt = n; return render();
      case 'shut': return shut();
      case 'sell': { setS((await api('sell', { uids: [n] })).state); SFX.coin(); return render(); }
      case 'sellall': { const u = S.inv.filter(o => U.flt < 0 || IT[o.i].t === U.flt).map(o => o.u); if (!u.length) return; setS((await api('sell', { uids: u })).state); SFX.coin(); return render(); }
      case 'sell1': { shut(); const j = await api('sell', { uids: [n] }); setS(j.state); SFX.coin(); return toast('Продано: +' + fmt(j.got)); }
      case 'again': shut(); render(); return openCase();
      case 'dep': return openDep();
      case 'pay': return pay(n);
      case 'wd': return openWd(n);
      case 'wdsend': { const j = await api('withdraw', { uid: n, nick: $('#wnick').value }); setS(j.state); shut(); toast('Заявка отправлена. Ждём подтверждения!'); return render(); }
      case 'bonus': { const j = await api('bonus', {}); setS(j.state); SFX.coin(); toast(j.msg); return render(); }
      case 'promo': { const j = await api('promo', { code: $('#pcode').value }); setS(j.state); SFX.win(2); toast('✅ ' + j.msg); return render(); }
      case 'pin': if (U.busy) return; U.sel.has(n) ? U.sel.delete(n) : U.sel.add(n); SFX.click(); fillInv(); fillWheel(); return fillBar();
      case 'selall': if (U.busy) return; S.inv.forEach(o => U.sel.add(o.u)); fillInv(); fillWheel(); return fillBar();
      case 'selno': if (U.busy) return; U.sel.clear(); fillInv(); fillWheel(); return fillBar();
      case 'tg': if (U.busy) return; U.tg = n; SFX.click(); fillWheel(); fillShop(); fillBar(); return toast('Цель: ' + IT[n].n);
      case 'mult': case 'pct': { if (U.busy) return; const s = stake(); if (!s) return toast('Сначала выбери брейнрота в инвентаре'); U.tg = near(a === 'mult' ? s * n : s * S.cfg.edge / n).id; SFX.click(); fillWheel(); fillShop(); return fillBar(); }
      case 'pane': U.pane = v; document.querySelector('.up').dataset.pane = v; document.querySelectorAll('.seg button').forEach(x => x.classList.toggle('on', x.dataset.v === v)); return;
      case 'cadd': U.cart[n] = (U.cart[n] || 0) + 1; SFX.click(); if (!$('#ov').hidden) openCart(); else fillShop(); return fillBar();
      case 'cdec': U.cart[n] = Math.max(0, (U.cart[n] || 0) - 1); if (!U.cart[n]) delete U.cart[n]; openCart(); fillShop(); return fillBar();
      case 'cdel': delete U.cart[n]; openCart(); fillShop(); return fillBar();
      case 'cclr': U.cart = {}; shut(); fillShop(); return fillBar();
      case 'cart': return openCart();
      case 'cbuy': { if (!cartN()) return; const j = await api('buy', { items: U.cart }); setS(j.state); U.cart = {}; shut(); SFX.coin(); toast('Куплено! Потрачено ' + fmt(j.paid)); if (U.tab === 'up') { fillInv(); fillShop(); fillBar(); } return; }
      case 'spin': return spin();
      case 'cfg': modal(null, 'Настройки рулетки', `<div style="width:100%"><label class="mu">Кнопки множителя (x)</label><div class="fm">${PR.xs.map((x, i) => `<input id="cx${i}" type="number" step="0.1" min="1.1" value="${x}">`).join('')}</div><label class="mu">Кнопки шанса (%)</label><div class="fm">${PR.ps.map((x, i) => `<input id="cp${i}" type="number" min="1" max="90" value="${x}">`).join('')}</div></div><button class="b" data-a="cfgsave" style="width:100%">Сохранить</button>`, 'Поставь любые значения — например x2 → x4. Своё значение можно ввести и в полях рядом с кнопками.', 'wide'); return;
      case 'cfgsave': { const xs = [0, 1, 2].map(i => parseFloat($('#cx' + i).value)).map(x => x > 1 ? x : 2), ps = [0, 1, 2].map(i => parseFloat($('#cp' + i).value)).map(x => x >= 1 && x <= 90 ? x : 50); PR.xs = xs; PR.ps = ps; savePR(); shut(); return render(); }
      case 'atab': U.ad = v; document.querySelectorAll('[data-a=atab]').forEach(x => x.classList.toggle('on', x.dataset.v === v)); return loadAd();
      case 'pcreate': { const kind = $('#pk').value, body = { kind, code: $('#pcd').value, value: +($('#pv').value || 0), case: +($('#pc').value || 0), qty: +($('#pq').value || 1) }; if ($('#pa')) { body.max_act = +$('#pa').value; body.hours = +$('#ph').value; } const j = await api('admin/promo/create', body); toast('Создан код ' + j.code); return loadAd(); }
      case 'ptoggle': await api('admin/promo/toggle', { code: v, on: b.dataset.on === '1' }); return loadAd();
      case 'puses': { const j = await api('admin/promo/uses', { code: v }); return modal(null, 'Активации ' + esc(v), '<button class="b" data-a="shut" style="width:100%">Закрыть</button>', j.list.length ? j.list.map(x => `${esc(x.u)} — ${fd(x.t)}`).join('<br>') : 'Пока никто не активировал', 'wide'); }
      case 'role': await api('admin/role', { username: $('#ru').value, role: +$('#rl').value }); toast('Сохранено'); return loadAd();
      case 'wdok': await api('admin/wd/resolve', { id: n, ok: true }); toast('Отмечено как выданное'); return loadAd();
      case 'wdno': { const note = prompt('Причина отказа (необязательно)') || ''; await api('admin/wd/resolve', { id: n, ok: false, note }); toast('Отклонено, брейнрот возвращён'); return loadAd(); }
      case 'setsave': { const set = {}; document.querySelectorAll('[data-set]').forEach(i => set[i.dataset.set] = +i.value); await api('admin/settings', { set }); toast('Настройки сохранены'); return; }
      case 'give': await api('admin/give', { username: $('#gu').value, amount: +$('#ga').value }); toast('Выдано'); return;
    }
  });
}
document.addEventListener('click', e => { if (e.target.id === 'ov') return shut(); const b = e.target.closest('[data-a]'); if (!b) return; e.preventDefault(); act(b.dataset.a, b.dataset.v, b); });
document.addEventListener('input', e => {
  const t = e.target;
  if (t.id === 'fmin' || t.id === 'fmax' || t.id === 'fq') { U.f = { min: +$('#fmin').value || 0, max: +$('#fmax').value || 0, q: $('#fq').value.trim() }; fillShop(); }
  else if (t.id === 'cx' || t.id === 'cp') { const s = stake(), x = parseFloat(t.value); if (!(x > 0)) return; if (!s) return toast('Сначала выбери брейнрота'); U.tg = near(t.id === 'cx' ? s * x : s * S.cfg.edge / Math.min(S.cfg.edge, x)).id; fillWheel(); fillShop(); fillBar(); }
});
document.addEventListener('change', e => { if (e.target.id === 'pk') { const k = e.target.value; $('#pvw').style.display = k === 'case' ? 'none' : ''; $('#pcw').style.display = $('#pqw').style.display = k === 'case' ? '' : 'none'; $('#pvl').textContent = k === 'coins' ? 'Монет' : 'Бонус, %'; } });
$('#mu').textContent = PR.mute ? '🔇' : '🔊';
$('#mu').onclick = () => { PR.mute ^= 1; savePR(); $('#mu').textContent = PR.mute ? '🔇' : '🔊'; };
setInterval(() => { if (U.tab === 'bon' && S && $('#bbtn')) { const l = bleft(), c = S.cfg, b = $('#bbtn'); b.disabled = l > 0; b.textContent = l > 0 ? 'Через ' + dur(l) : 'Забрать +' + fmt(c.bamt); } }, 1000);
(async () => {
  try {
    const cat = await fetch('/static/catalog.json').then(r => r.json()); IT = cat.items; TR = cat.tiers; K = await api('cases');
    K.cats.forEach(c => c.cases.forEach(x => CS[x.id] = x)); await refresh(); render();
  } catch (e) { $('#m').innerHTML = `<div class="emp">${esc(e.message)}<br><br>Открой игру через Telegram-бота.</div>`; }
})();
