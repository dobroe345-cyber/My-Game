#!/usr/bin/env python3
"""Brainrot Vault — сервер Telegram Mini App.
Только стандартная библиотека Python: ничего устанавливать не нужно.
Запуск:  python server.py   (токен бота — в переменной окружения BOT_TOKEN)."""
import os, sys, json, hmac, hashlib, time, sqlite3, threading, secrets, random, re, math, traceback
import urllib.parse, urllib.request, urllib.error, mimetypes
from contextlib import contextmanager
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATIC = BASE / 'static'

# ───────────────────────── НАСТРОЙКИ (через переменные окружения) ─────────────────────────
BOT_TOKEN = os.environ.get('BOT_TOKEN', '').strip()          # токен бота из @BotFather
OWNER_USERNAME = os.environ.get('OWNER_USERNAME', 'Tuke5669').lstrip('@').lower()
OWNER_ID_ENV = os.environ.get('OWNER_ID', '').strip()        # необязательно: числовой id владельца
PUBLIC_URL = (os.environ.get('PUBLIC_URL') or os.environ.get('RENDER_EXTERNAL_URL') or '').rstrip('/')
DB_PATH = os.environ.get('DB_PATH') or ('/data/game.db' if os.path.isdir('/data') else str(BASE / 'game.db'))
PORT = int(os.environ.get('PORT', '8000'))
DEV_MODE = os.environ.get('DEV_MODE') == '1'                  # ТОЛЬКО для проверки на своём компьютере
TG_API = os.environ.get('TELEGRAM_API_BASE', 'https://api.telegram.org')
TG_CHANNEL = os.environ.get('TG_CHANNEL', '').strip()         # напр. @mychannel — для кейса «Подписка»
WEBHOOK_SECRET = hashlib.sha256(('wh:' + BOT_TOKEN).encode()).hexdigest()[:32]

DEFAULTS = {            # меняются в админ-меню (владелец)
    'start_balance': 100, 'bonus_on': 1, 'bonus_amount': 50, 'bonus_cd': 600,
    'free_on': 1, 'rate': 5, 'min_withdraw': 300, 'markup': 5,
}
FREE_CD = 24 * 3600     # бесплатные кейсы — раз в сутки
UP_EDGE = 90            # апгрейд: шанс = ставка / цель × 90 %
PAYBACK = 0.68          # средний возврат кейса (68 % от цены)
STAR_PACKS = [20, 50, 100, 250, 500, 1000]

# Уровни прав. dep — максимальный бонус к депозиту (%), acts — макс. активаций, hours — срок жизни промо,
# coins — макс. монет в одном промо, case — макс. цена кейса в промо на кейс.
ROLES = {
    1: dict(name='Блогер',   dep=5,  acts=10,  hours=48, coins=50,  case=150),
    2: dict(name='Помощник', dep=10, acts=50,  hours=48, coins=150, case=1500),
    3: dict(name='Партнёр',  dep=25, acts=100, hours=48, coins=500, case=10000),
    4: dict(name='Владелец', dep=1000, acts=0, hours=0,  coins=10**9, case=10**9),
}

# ───────────────────────── БАЗА ДАННЫХ ─────────────────────────
SCHEMA = '''
create table if not exists users(id integer primary key, username text, first_name text, last_name text, photo text,
  balance integer not null default 0, created integer, bonus_at integer default 0, dep_bonus integer default 0,
  st_c integer default 0, st_u integer default 0, st_w integer default 0, best_p integer default 0, best_n text default '');
create table if not exists inv(uid integer primary key autoincrement, user_id integer not null, item integer not null, ts integer);
create index if not exists inv_u on inv(user_id);
create table if not exists hist(id integer primary key autoincrement, user_id integer, ts integer, kind text, msg text, delta integer);
create index if not exists hist_u on hist(user_id, id);
create table if not exists promos(code text primary key, kind text, value integer, case_id integer, qty integer, max_act integer,
  expires integer, creator integer, creator_name text, created integer, active integer default 1);
create table if not exists promo_uses(id integer primary key autoincrement, code text, user_id integer, uname text, ts integer, unique(code, user_id));
create table if not exists withdrawals(id integer primary key autoincrement, user_id integer, tg text, roblox text, item integer,
  price integer, status text default 'pending', created integer, resolved integer, note text default '');
create table if not exists payments(charge text primary key, user_id integer, stars integer, coins integer, ts integer);
create table if not exists settings(key text primary key, value text);
create table if not exists staff(username text primary key, user_id integer, role integer, granted integer);
create table if not exists freecases(user_id integer, case_id integer, qty integer, primary key(user_id, case_id));
create table if not exists cd(user_id integer, key text, ts integer, primary key(user_id, key));
'''
LOCK = threading.RLock()
DB = None


def db_init():
    global DB
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    DB = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    DB.row_factory = sqlite3.Row
    DB.execute('pragma journal_mode=wal')
    DB.executescript(SCHEMA)


@contextmanager
def tx():
    with LOCK:
        DB.execute('begin immediate')
        try:
            yield DB
        except BaseException:
            DB.execute('rollback')
            raise
        else:
            DB.execute('commit')


class ApiError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


def err(msg, code=400):
    raise ApiError(msg, code)


def now():
    return int(time.time())


def setting(k):
    with LOCK:
        r = DB.execute('select value from settings where key=?', (k,)).fetchone()
    return int(r['value']) if r else DEFAULTS[k]


def raw_setting(k):
    with LOCK:
        r = DB.execute('select value from settings where key=?', (k,)).fetchone()
    return r['value'] if r else None


def owner_id():
    return int(OWNER_ID_ENV) if OWNER_ID_ENV.isdigit() else (int(raw_setting('owner_id')) if raw_setting('owner_id') else 0)


# ───────────────────────── TELEGRAM BOT API ─────────────────────────
def tg(method, **params):
    if not BOT_TOKEN:
        raise RuntimeError('BOT_TOKEN не задан')
    req = urllib.request.Request(f'{TG_API}/bot{BOT_TOKEN}/{method}', data=json.dumps(params).encode(),
                                 headers={'Content-Type': 'application/json'})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=35))
    except urllib.error.HTTPError as e:
        r = json.loads(e.read().decode() or '{}')
    if not r.get('ok'):
        raise RuntimeError(f'Telegram {method}: {r.get("description")}')
    return r['result']


def notify(uid, text, **kw):
    if not (BOT_TOKEN and uid):
        return
    try:
        tg('sendMessage', chat_id=uid, text=text, **kw)
    except Exception as e:
        print('notify:', e)


def check_init_data(init):
    """Проверка подписи Telegram Mini App (initData)."""
    try:
        pairs = dict(urllib.parse.parse_qsl(init, keep_blank_values=True))
        got = pairs.pop('hash', '')
        dcs = '\n'.join(f'{k}={v}' for k, v in sorted(pairs.items()))
        secret = hmac.new(b'WebAppData', BOT_TOKEN.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest(), got):
            return None
        if now() - int(pairs.get('auth_date', 0)) > 86400:
            return None
        return json.loads(pairs['user'])
    except Exception:
        return None


# ───────────────────────── КАТАЛОГ И КЕЙСЫ ─────────────────────────
CATALOG = json.load(open(STATIC / 'catalog.json', encoding='utf-8'))
ITEMS = CATALOG['items']
NM = {i['n']: i for i in ITEMS}
RNG = random.SystemRandom()


def T(*names):
    return [NM[n] for n in names if n in NM]


def TIER(t):
    return [i for i in ITEMS if i['t'] == t]


def buyp(p, mk):
    return (p * (100 + mk) + 50) // 100        # цена в магазине: стоимость + наценка (округление как в JS)


def near(lst, v):
    return min(lst, key=lambda i: abs(math.log(i['p'] / v)))


def spread(a, m):
    m = min(m, len(a))
    out = []
    for i in range(m):
        x = a[round(i * (len(a) - 1) / max(1, m - 1))]
        if x not in out:
            out.append(x)
    return out


def contents(c):
    """Состав и шансы кейса: тематические + случайные брейнроты, средний возврат ≈ PAYBACK, редкий «хук»."""
    P = c['calc']
    th = sorted(c['th'], key=lambda i: i['p'])
    tg_ = min(P * 7, 200000)
    hk = near(ITEMS, tg_)
    if th:
        t = near(th, tg_)
        if abs(math.log(t['p'] / tg_)) < math.log(2.5):
            hk = t
    tp = spread([i for i in th if i is not hk and P * .15 <= i['p'] <= P * 4], 4)
    rp = spread(sorted([i for i in ITEMS if P * .2 <= i['p'] <= P * 1.4 and i is not hk and i not in tp],
                       key=lambda i: i['p']), 11 - len(tp))
    u = rp + tp
    h = .0012 if hk['p'] > 1e5 else .003
    aff = {i['id'] for i in th if i['p'] <= P * 2.5}
    lo_s, hi_s = c['share']

    def weights(k):
        w = [(i['p'] / P) ** -k for i in u]
        tot = sum(w)
        ts = sum(x for x, i in zip(w, u) if i['id'] in aff)
        if ts > 0 and tot > ts:
            sh = ts / tot
            t2 = min(hi_s, max(lo_s, sh))
            if t2 != sh:
                f = t2 / (1 - t2) * (tot - ts) / ts
                w = [x * f if i['id'] in aff else x for x, i in zip(w, u)]
        return w

    lo, hi = 0.0, 9.0
    for _ in range(50):
        k = (lo + hi) / 2
        w = weights(k)
        ev = (1 - h) * sum(i['p'] * x for i, x in zip(u, w)) / sum(w) + h * hk['p']
        if ev > PAYBACK * P:
            lo = k
        else:
            hi = k
    w = weights((lo + hi) / 2)
    s = sum(w)
    thids = {i['id'] for i in th}
    r = [(i['id'], (1 - h) * x / s, i['id'] in thids) for i, x in zip(u, w)] + [(hk['id'], h, hk['id'] in thids)]
    return sorted(r, key=lambda z: -ITEMS[z[0]]['p'])


SH, SR = (.2, .4), (.55, .85)
CATS = [('free', '🆓 Бесплатные', 'Выполни простое условие и открой кейс бесплатно. Скоро все бесплатное уберём.'),
        ('start', '🚀 Для старта', 'Дешёвые кейсы для первых шагов — обычные и редкие брейнроты.'),
        ('rarity', '💎 По редкости', 'Чем выше редкость кейса, тем ценнее брейнроты внутри.'),
        ('season', '🎄 Сезонные', 'Кейсы к сезонам и праздникам со своей атмосферой.'),
        ('theme', '🎬 Тематические', 'Аниме, армия, неон, космос и хоррор — выбирай настроение.'),
        ('classic', '🧠 Классические', 'Тематические брейнроты по мотивам сундуков + случайные.')]
# (картинка n/#, название, категория, тип, цена, расчётная цена, цвет, тема, доля темы)
NEWC = [
    (0, 'Бесплатный', 'free', 'free', 0, 20, '#4db8ff', [], SH),
    (1, 'Подписка', 'free', 'sub', 0, 45, '#3aa0ff', [], SH),
    (2, 'По тегу', 'free', 'soon', 0, 70, '#b04dff', [], SH),
    (3, 'Поделись', 'free', 'soon', 0, 90, '#3ddc5a', [], SH),
    (4, 'Простой', 'start', 'paid', 15, 15, '#ffc83d', [], SH),
    (6, 'Средний', 'start', 'paid', 70, 70, '#b04dff', [], SH),
    (7, 'Редкий', 'rarity', 'paid', 150, 150, '#3aa0ff', TIER(1), SR),
    (8, 'Эпик', 'rarity', 'paid', 550, 550, '#d24dff', TIER(2), SR),
    (9, 'Легендарный', 'rarity', 'paid', 2200, 2200, '#ffb020', TIER(3), SR),
    (10, 'Мифический', 'rarity', 'paid', 9000, 9000, '#ff3d41', TIER(4), SR),
    (11, 'Бессмертный', 'rarity', 'paid', 30000, 30000, '#18d6c8', TIER(5), SR),
    (15, 'Лето', 'season', 'paid', 120, 120, '#ffcc33', T('Pipi Kiwi', 'Pipi Avocado', 'Pinealotto Fruttarino', 'Avocadini Antilopini', 'Avocadini Guffo', 'Perochello Lemonchello', 'Pi Pi Watermelon', 'Tigrilini Watermelini', 'Capi Taco', 'Capibaro Celestino', 'Chicleteira Surfeiteira', 'Flippo Marino'), SH),
    (12, 'Зима', 'season', 'paid', 350, 350, '#6cc8ff', T('Salamino Penguino', 'Penguin Tree', 'Penguino Cocosino', 'Pogo Pogo Penguin', 'Pengolino Nuvoletto', 'Pin Pin Pengu', 'Frostino Vampiro', 'Yetimatic'), SH),
    (14, 'Рождество', 'season', 'paid', 3000, 3000, '#e0463c', T('Noobini Santanini', 'Jingle Jingle Sahur', 'Tree Tree Tree Sahur', 'Chicleteira Noelteira', 'Los Jolly Combinasionas', 'Penguin Tree', 'Frostino Vampiro'), SH),
    (13, 'Хэллоуин', 'season', 'paid', 18000, 18000, '#ff8a1f', T('Jacko Spaventosa', 'Penguino Pumpkino', 'Jacko Jack Jack', 'Spooky and Pumpky', 'La Spooky Grande', 'Los Spooky Combinasionas', 'Vampira Cappucina', 'Draculino', 'Headless Horseman'), SH),
    (5, 'Аниме', 'theme', 'paid', 800, 800, '#ff4b3a', T('Cappuccino Assassino', 'Syrup Samurai', 'Sigma Boy', 'Sigma Girl', 'Chef Crabracadabra', 'Ballerina Cappuccina', 'Bandito Axolito', 'Gangster Footera', 'Bandito Bobritto'), SH),
    (17, 'Армия', 'theme', 'paid', 10000, 10000, '#8aa05a', T('Bombardiro Crocodilo', 'Rhino Helicopterino', 'Tractoro Dinosauro', 'Bombombini Gusini', 'Bulbito Bandito Traktorito', 'Brutto Gialutto', 'Capitano Americano', '4th Bros', 'Aquarino', 'Stoppo Luminino'), SH),
    (18, 'Неон', 'theme', 'paid', 40000, 40000, '#7a6bff', T('Orbi Mochi', 'Arcadopus', 'Rubiko and Kubiko', 'La Fuse Machine', 'Var Var Var', 'Rockarino Rockara', 'Gelatina Volatina', 'Pop Pop Petalini', 'Chillin Chili', 'Bumbatron', 'Grabatron', 'Orchidox'), SH),
    (16, 'Космос', 'theme', 'paid', 15000, 15000, '#a259ff', T('Tralalero Tralala', 'Tralalita Tralala', 'Aquanaut', 'Cacasito Satalito', 'Orbi Mochi', 'Odin Din Din Dun', 'Trenostruzzo Turbo 3000', 'Carrotini Brainini'), SH),
    (19, 'Хоррор', 'theme', 'paid', 22000, 22000, '#ff2d3d', T('Headless Horseman', 'Draculino', 'Vampira Cappucina', 'Frostino Vampiro', 'Los Spooky Combinasionas', 'La Spooky Grande', 'Jacko Spaventosa', 'Spooky and Pumpky', 'Mummio Rappitto'), SH),
]
CLASSIC = [  # (картинка c/#, название, цвет, тема)
    (0, 'Космический акулёнок', '#a259ff', ['Tralalero Tralala', 'Tralalita Tralala', 'Aquanaut', 'Cacasito Satalito', 'Orbi Mochi', 'Odin Din Din Dun', 'Trenostruzzo Turbo 3000']),
    (1, 'Банановый', '#ffcc33', ['Bananita Dolphinita', 'Chimpanzini Bananini', 'Pandaccini Bananini', 'Bananito Bandito', 'Tukanno Bananno', 'Orangutini Ananassini', 'Pinealotto Fruttarino', 'Pineaplino']),
    (2, 'Тунг-Тунг', '#ff4b3a', ['Ta Ta Ta Ta Sahur', 'Ti Ti Ti Sahur', 'Te Te Te Sahur', 'Jingle Jingle Sahur', 'Tree Tree Tree Sahur', 'Ref Ref Ref Sahur']),
    (3, 'Ледяной', '#4db8ff', ['Pengolino Nuvoletto', 'Frostino Vampiro', 'Pin Pin Pengu', 'Yetimatic', 'Salamino Penguino']),
    (4, 'Болотный', '#4ddc3a', ['Tartaragno', 'Boneca Ambalabu', 'Frogo Elfo', 'Frogato Pirato', 'Magi Ribbitini', 'Bulbito Bandito Traktorito']),
    (5, 'Тыквенный', '#ff8a1f', ['Jacko Spaventosa', 'Penguino Pumpkino', 'Jacko Jack Jack', 'Spooky and Pumpky', 'La Spooky Grande', 'Los Spooky Combinasionas', 'Vampira Cappucina', 'Draculino', 'Headless Horseman']),
    (6, 'Санта', '#e0463c', ['Noobini Santanini', 'Jingle Jingle Sahur', 'Tree Tree Tree Sahur', 'Chicleteira Noelteira', 'Los Jolly Combinasionas', 'Penguin Tree', 'Frostino Vampiro']),
    (7, 'Геймерский', '#7a6bff', ['Noobini Pizzanini', 'Noobini Santanini', 'Raccooni Jandelini', 'Chimpanzini Bananini', 'Los Noobinis']),
    (8, 'Фараон', '#ffb21a', ['Mummio Rappitto', 'Frigo Camelo', 'Qamar Camelamp', 'Летающий ковёр', 'Tracoducotulu Delapeladustuz', 'Cavallo Virtuoso', 'Cacto Hipopotamo']),
    (9, 'Валентинка', '#ff4d8d', ['Los Cupids', 'Chocco Bunny', 'Sigma Girl', 'Strawberrelli Flamingelli', 'Pengolino Nuvoletto', 'Pin Pin Pengu', 'Pogo Pogo Penguin', 'Cupcake Koala']),
    (10, 'Пасхальный кролик', '#8fb8ff', ['Cupcake Koala', 'Holy Arepa', 'Chocco Bunny', 'Cocosini Mama', 'Pipi Avocado', 'Candini Fluffini', 'Gelato Lumacho']),
    (11, 'Пришелец', '#3ddc5a', ['Cacasito Satalito', 'Aquanaut', 'Orbi Mochi', 'Rhino Helicopterino', 'Bombombini Gusini', 'Bombardiro Crocodilo', 'Trenostruzzo Turbo 3000']),
    (12, 'Океан', '#31c8ff', ['Marino Submarino', 'Aquarino', 'Flippo Marino', 'Peschito Machito', 'Orcalero Orcala', 'Blueberrinni Octopusini', 'Pelican Pachetto', 'Tartaragno', 'Bananita Dolphinita']),
    (13, 'Драконий', '#ff5a2a', ['Dragon Cannelloni', 'Hydra Serpent', 'Los Dragons', 'Rexino Ramino', 'Tractoro Dinosauro', 'Trippi Troppi Troppa Trippa']),
    (14, 'GG', '#8a5cff', ['Pretzo Robo', 'Bumbatron', 'Grabatron', 'La Fuse Machine', 'La Craft Machine', 'Var Var Var', 'Arcadopus', 'Rubiko and Kubiko']),
    (15, 'Снеговик', '#6cc8ff', ['Salamino Penguino', 'Penguin Tree', 'Penguino Cocosino', 'Pogo Pogo Penguin', 'Noobini Santanini', 'Pengolino Nuvoletto']),
    (16, 'Пиратский', '#e0952b', ['Frogato Pirato', 'Moby Bros', 'Bandito Bobritto', 'Bandito Axolito', 'Cappuccino Assassino', 'Syrup Samurai', 'Los Crocodillitos', 'Gangster Footera']),
    (17, 'Галактика', '#b04dff', ['Carrotini Brainini', 'Orbi Mochi', 'Cacasito Satalito', 'Aquanaut', 'Odin Din Din Dun', 'Trenostruzzo Turbo 3000', 'Tralalita Tralala']),
    (18, 'Капибара', '#28d6c8', ['Pipi Kiwi', 'Pipi Avocado', 'Pinealotto Fruttarino', 'Avocadini Antilopini', 'Avocadini Guffo', 'Perochello Lemonchello', 'Pi Pi Watermelon', 'Tigrilini Watermelini', 'Capi Taco', 'Capibaro Celestino']),
    (19, 'Тайна', '#7a2bd6', ['Mythic Lucky Block', 'Brainrot God Lucky Block']),
]
LAD = [20, 45, 90, 160, 280, 450, 700, 1100, 1700, 2600, 3800, 5500, 8000, 11000, 15000, 20000, 27000, 36000, 50000, 75000]
CASES, CASE = [], {}


def build_cases():
    def med(c):
        if c['name'] == 'Тайна' or not c['th']:
            return 1e12
        a = sorted(i['p'] for i in c['th'])
        return a[len(a) // 2]
    for n, (ci, name, cat, kind, price, calc, col, th, sh) in enumerate(NEWC):
        CASES.append(dict(id=ci, cat=cat, name=name, kind=kind, price=price, calc=calc, color=col, th=th, share=sh, chest=f'n/{ci}.webp'))
    cl = [dict(cat='classic', name=name, kind='paid', color=col, th=T(*th), share=SH, chest=f'c/{ci}.webp', cid=ci) for ci, name, col, th in CLASSIC]
    for k, c in enumerate(sorted(cl, key=med)):
        c['price'] = c['calc'] = LAD[k]
        c['id'] = 20 + c['cid']
        CASES.append(c)
    for c in CASES:
        c['r'] = contents(c)
        CASE[c['id']] = c


def cases_payload():
    cats = []
    for cid, title, desc in CATS:
        cs = [c for c in CASES if c['cat'] == cid]
        cs.sort(key=lambda c: c['calc'])
        cats.append({'id': cid, 'title': title, 'desc': desc, 'cases': [
            {'id': c['id'], 'n': c['name'], 'p': c['price'], 'k': c['kind'], 'img': c['chest'], 'col': c['color'],
             'r': [[i, round(ch, 5), 1 if t else 0] for i, ch, t in c['r']]} for c in cs]})
    return {'cats': cats}


def roll(r):
    x, a = RNG.random(), 0.0
    for i, ch, _ in r:
        a += ch
        if x < a:
            return i
    return r[-1][0]


# ───────────────────────── ПОЛЬЗОВАТЕЛИ И СОСТОЯНИЕ ─────────────────────────
def log(uid, kind, msg, delta=0):
    DB.execute('insert into hist(user_id,ts,kind,msg,delta) values(?,?,?,?,?)', (uid, now(), kind, msg, delta))


def balance(uid):
    return DB.execute('select balance from users where id=?', (uid,)).fetchone()[0]


def add_bal(uid, d):
    DB.execute('update users set balance=balance+? where id=?', (d, uid))


def role_of(uid):
    with LOCK:
        if owner_id() and owner_id() == uid:
            return 4
        r = DB.execute('select role from staff where user_id=?', (uid,)).fetchone()
        return r['role'] if r else 0


def upsert_user(u):
    uid = u['id']
    un = (u.get('username') or '').lower()
    with tx():
        if DB.execute('select 1 from users where id=?', (uid,)).fetchone():
            DB.execute('update users set username=?,first_name=?,last_name=?,photo=? where id=?',
                       (u.get('username') or '', u.get('first_name') or '', u.get('last_name') or '', u.get('photo_url') or '', uid))
        else:
            sb = setting('start_balance')
            DB.execute('insert into users(id,username,first_name,last_name,photo,balance,created) values(?,?,?,?,?,?,?)',
                       (uid, u.get('username') or '', u.get('first_name') or '', u.get('last_name') or '', u.get('photo_url') or '', sb, now()))
            if sb:
                log(uid, 'bonus', 'Стартовый бонус', sb)
        if un and un == OWNER_USERNAME and not owner_id():
            DB.execute('insert or replace into settings(key,value) values("owner_id",?)', (str(uid),))
        if un:
            DB.execute('update staff set user_id=? where username=? and (user_id is null or user_id=?)', (uid, un, uid))


def state_of(uid):
    with LOCK:
        u = DB.execute('select * from users where id=?', (uid,)).fetchone()
        role = role_of(uid)
        inv = [{'u': r['uid'], 'i': r['item']} for r in DB.execute('select uid,item from inv where user_id=? order by uid', (uid,))]
        hist = [{'t': r['ts'], 'k': r['kind'], 'm': r['msg'], 'd': r['delta']} for r in
                DB.execute('select * from hist where user_id=? order by id desc limit 40', (uid,))]
        wd = [{'id': r['id'], 'item': r['item'], 'price': r['price'], 'nick': r['roblox'], 'st': r['status'], 't': r['created'], 'note': r['note']}
              for r in DB.execute('select * from withdrawals where user_id=? order by id desc limit 15', (uid,))]
        free = {r['case_id']: r['qty'] for r in DB.execute('select case_id,qty from freecases where user_id=? and qty>0', (uid,))}
        cd = {r['key'][4:]: r['ts'] for r in DB.execute('select key,ts from cd where user_id=? and key like "case%" and ts>?', (uid, now()))}
        left = max(0, u['bonus_at'] + setting('bonus_cd') - now())
        return {
            'me': {'id': uid, 'name': ((u['first_name'] or '') + ' ' + (u['last_name'] or '')).strip() or u['username'] or 'Игрок',
                   'un': u['username'], 'photo': u['photo'], 'role': role, 'rname': ROLES[role]['name'] if role else ''},
            'lim': ROLES[role] if 0 < role < 4 else None, 'bal': u['balance'], 'inv': inv, 'hist': hist, 'wd': wd, 'free': free, 'cd': cd, 'depb': u['dep_bonus'],
            'st': {'c': u['st_c'], 'u': u['st_u'], 'w': u['st_w'], 'bn': u['best_n'], 'bp': u['best_p']},
            'cfg': {'rate': setting('rate'), 'minwd': setting('min_withdraw'), 'mk': setting('markup'), 'bon': setting('bonus_on'),
                    'bamt': setting('bonus_amount'), 'bcd': setting('bonus_cd'), 'bleft': left, 'free': setting('free_on'), 'packs': STAR_PACKS, 'edge': UP_EDGE,
                    'srv': now()},
        }


# ───────────────────────── ИГРОВЫЕ МЕТОДЫ ─────────────────────────
def fmt_dur(s):
    s = int(s)
    return f'{s // 3600} ч {s % 3600 // 60} мин' if s >= 3600 else f'{s // 60} мин {s % 60} с'


def a_state(U, b):
    return state_of(U['id'])


def a_cases(U, b):
    return CASES_PAYLOAD


def a_open(U, b):
    c = CASE.get(int(b.get('case', -1)))
    if not c:
        err('Кейс не найден')
    uid = U['id']
    if c['kind'] == 'soon':
        err('Этот кейс появится позже')
    if c['kind'] == 'sub':
        if not (TG_CHANNEL and BOT_TOKEN):
            err('Кейс «Подписка» скоро будет доступен')
        try:
            ok = tg('getChatMember', chat_id=TG_CHANNEL, user_id=uid).get('status') in ('member', 'administrator', 'creator')
        except Exception:
            err('Не удалось проверить подписку, попробуй позже')
        if not ok:
            err('Сначала подпишись на канал ' + TG_CHANNEL)
    with tx():
        paid = 0
        if c['kind'] in ('free', 'sub'):
            if not setting('free_on'):
                err('Бесплатные кейсы отключены')
            r = DB.execute('select ts from cd where user_id=? and key=?', (uid, f'case{c["id"]}')).fetchone()
            if r and r['ts'] > now():
                err('Кейс будет доступен через ' + fmt_dur(r['ts'] - now()))
            DB.execute('insert or replace into cd(user_id,key,ts) values(?,?,?)', (uid, f'case{c["id"]}', now() + FREE_CD))
        else:
            fr = DB.execute('select qty from freecases where user_id=? and case_id=?', (uid, c['id'])).fetchone()
            if fr and fr['qty'] > 0:
                DB.execute('update freecases set qty=qty-1 where user_id=? and case_id=?', (uid, c['id']))
            else:
                if balance(uid) < c['price']:
                    err('Не хватает монет')
                add_bal(uid, -c['price'])
                paid = c['price']
        win = ITEMS[roll(c['r'])]
        new = DB.execute('insert into inv(user_id,item,ts) values(?,?,?)', (uid, win['id'], now())).lastrowid
        DB.execute('update users set st_c=st_c+1 where id=?', (uid,))
        if win['p'] >= DB.execute('select best_p from users where id=?', (uid,)).fetchone()[0]:
            DB.execute('update users set best_p=?,best_n=? where id=?', (win['p'], win['n'], uid))
        log(uid, 'case', f'«{c["name"]}»: {win["n"]}', win['p'] - paid)
    return {'win': win['id'], 'uid': new, 'state': state_of(uid)}


def owned(uid, uids):
    uids = list(dict.fromkeys(int(x) for x in uids))[:200]
    if not uids:
        err('Выбери брейнротов')
    q = ','.join('?' * len(uids))
    rows = DB.execute(f'select uid,item from inv where user_id=? and uid in ({q})', (uid, *uids)).fetchall()
    if len(rows) != len(uids):
        err('Часть предметов не найдена')
    return rows, q, uids


def a_sell(U, b):
    uid = U['id']
    with tx():
        rows, q, uids = owned(uid, b.get('uids', []))
        total = sum(ITEMS[r['item']]['p'] for r in rows)
        DB.execute(f'delete from inv where user_id=? and uid in ({q})', (uid, *uids))
        add_bal(uid, total)
        log(uid, 'sell', ('Продал ' + ITEMS[rows[0]['item']]['n']) if len(rows) == 1 else f'Продал {len(rows)} шт.', total)
    return {'state': state_of(uid), 'got': total}


def a_buy(U, b):
    uid = U['id']
    lines = []
    for k, v in (b.get('items') or {}).items():
        k, v = int(k), int(v)
        if not (0 <= k < len(ITEMS)) or v < 1 or v > 50:
            err('Некорректная корзина')
        lines.append((k, v))
    if not lines or sum(v for _, v in lines) > 100:
        err('Корзина пуста или слишком большая')
    mk = setting('markup')
    total = sum(buyp(ITEMS[k]['p'], mk) * v for k, v in lines)
    with tx():
        if balance(uid) < total:
            err('Не хватает монет')
        add_bal(uid, -total)
        for k, v in lines:
            for _ in range(v):
                DB.execute('insert into inv(user_id,item,ts) values(?,?,?)', (uid, k, now()))
        log(uid, 'buy', f'Купил {sum(v for _, v in lines)} шт. в магазине', -total)
    return {'state': state_of(uid), 'paid': total}


def a_upgrade(U, b):
    uid = U['id']
    target = ITEMS[int(b.get('target', -1))] if 0 <= int(b.get('target', -1)) < len(ITEMS) else err('Цель не найдена')
    with tx():
        rows, q, uids = owned(uid, b.get('uids', []))
        stake = sum(ITEMS[r['item']]['p'] for r in rows)
        if target['p'] <= stake:
            err('Цель должна быть дороже ставки')
        chance = max(.5, min(90.0, stake / target['p'] * UP_EDGE))
        win = RNG.random() * 100 < chance
        DB.execute(f'delete from inv where user_id=? and uid in ({q})', (uid, *uids))
        DB.execute('update users set st_u=st_u+1 where id=?', (uid,))
        if win:
            DB.execute('insert into inv(user_id,item,ts) values(?,?,?)', (uid, target['id'], now()))
            DB.execute('update users set st_w=st_w+1 where id=?', (uid,))
            log(uid, 'up', f'Апгрейд удался: {len(rows)} шт. → {target["n"]}', target['p'] - stake)
        else:
            log(uid, 'up', f'Апгрейд не удался: потеряно {len(rows)} шт.', -stake)
    return {'win': win, 'chance': chance, 'state': state_of(uid)}


def a_withdraw(U, b):
    uid = U['id']
    nick = (b.get('nick') or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_]{3,20}', nick):
        err('Ник Roblox: 3–20 символов (латиница, цифры и _)')
    mn = setting('min_withdraw')
    with tx():
        row = DB.execute('select uid,item from inv where user_id=? and uid=?', (uid, int(b.get('uid', 0)))).fetchone()
        if not row:
            err('Брейнрот не найден')
        it = ITEMS[row['item']]
        if it['p'] < mn:
            err(f'Вывод доступен от {mn} монет')
        if DB.execute('select count(*) from withdrawals where user_id=? and status="pending"', (uid,)).fetchone()[0] >= 10:
            err('Слишком много активных заявок, дождись обработки')
        DB.execute('delete from inv where uid=?', (row['uid'],))
        wid = DB.execute('insert into withdrawals(user_id,tg,roblox,item,price,created) values(?,?,?,?,?,?)',
                         (uid, U.get('username') or '', nick, it['id'], it['p'], now())).lastrowid
        log(uid, 'wd', f'Заявка на вывод #{wid}: {it["n"]} → {nick}', 0)
    if owner_id():
        notify(owner_id(), f'🆕 Заявка на вывод #{wid}\n@{U.get("username") or uid} → Roblox: {nick}\n{it["n"]} ({it["p"]} монет)')
    return {'state': state_of(uid)}


def a_bonus(U, b):
    uid = U['id']
    with tx():
        if not setting('bonus_on'):
            err('Бесплатный бонус отключён')
        u = DB.execute('select bonus_at from users where id=?', (uid,)).fetchone()
        cd = setting('bonus_cd')
        if now() - u['bonus_at'] < cd:
            err('Бонус будет доступен через ' + fmt_dur(cd - (now() - u['bonus_at'])))
        amt = setting('bonus_amount')
        DB.execute('update users set bonus_at=? where id=?', (now(), uid))
        add_bal(uid, amt)
        log(uid, 'bonus', 'Бонус монет', amt)
    return {'state': state_of(uid), 'msg': f'+{amt} монет'}


def a_promo(U, b):
    uid = U['id']
    code = (b.get('code') or '').strip().upper()
    with tx():
        p = DB.execute('select * from promos where code=?', (code,)).fetchone()
        if not p or not p['active']:
            err('Промокод не найден или отключён')
        if p['expires'] and p['expires'] < now():
            err('Срок действия промокода закончился')
        if p['creator'] == uid:
            err('Нельзя активировать свой промокод')
        used = DB.execute('select count(*) from promo_uses where code=?', (code,)).fetchone()[0]
        if p['max_act'] and used >= p['max_act']:
            err('Лимит активаций исчерпан')
        if DB.execute('select 1 from promo_uses where code=? and user_id=?', (code, uid)).fetchone():
            err('Ты уже активировал этот промокод')
        DB.execute('insert into promo_uses(code,user_id,uname,ts) values(?,?,?,?)', (code, uid, U.get('username') or '', now()))
        if p['kind'] == 'coins':
            add_bal(uid, p['value'])
            msg = f'+{p["value"]} монет'
        elif p['kind'] == 'case':
            DB.execute('insert into freecases(user_id,case_id,qty) values(?,?,?) on conflict(user_id,case_id) do update set qty=qty+?',
                       (uid, p['case_id'], p['qty'], p['qty']))
            msg = f'Бесплатных открытий «{CASE[p["case_id"]]["name"]}»: {p["qty"]}'
        else:
            DB.execute('update users set dep_bonus=max(dep_bonus,?) where id=?', (p['value'], uid))
            msg = f'+{p["value"]}% к следующему пополнению'
        log(uid, 'bonus', f'Промокод {code}: {msg}', p['value'] if p['kind'] == 'coins' else 0)
    return {'state': state_of(uid), 'msg': msg}


# ───────────────────────── ПЛАТЕЖИ (TELEGRAM STARS) ─────────────────────────
def a_deposit(U, b):
    stars = int(b.get('stars', 0))
    if not 5 <= stars <= 10000:
        err('Сумма от 5 до 10000 ⭐')
    if not BOT_TOKEN:
        err('Бот ещё не настроен (нет BOT_TOKEN)')
    st = state_of(U['id'])
    coins = int(stars * st['cfg']['rate'] * (1 + st['depb'] / 100))
    try:
        link = tg('createInvoiceLink', title='Пополнение баланса', description=f'{stars} ⭐ → {coins} монет',
                  payload=f'dep:{U["id"]}:{stars}:{secrets.token_hex(4)}', provider_token='', currency='XTR',
                  prices=[{'label': 'Монеты', 'amount': stars}])
    except Exception as e:
        print('invoice:', e)
        err('Не удалось создать счёт, попробуй позже')
    return {'link': link, 'coins': coins}


def credit_payment(uid, sp):
    parts = str(sp.get('invoice_payload', '')).split(':')
    if sp.get('currency') != 'XTR' or len(parts) < 3 or parts[0] != 'dep' or int(parts[1]) != uid:
        print('payment ignored', sp)
        return
    stars, charge = int(sp['total_amount']), sp['telegram_payment_charge_id']
    with tx():
        if DB.execute('select 1 from payments where charge=?', (charge,)).fetchone():
            return
        u = DB.execute('select dep_bonus from users where id=?', (uid,)).fetchone()
        if not u:
            return
        bonus = u['dep_bonus']
        coins = int(stars * setting('rate') * (1 + bonus / 100))
        add_bal(uid, coins)
        DB.execute('update users set dep_bonus=0 where id=?', (uid,))
        DB.execute('insert into payments(charge,user_id,stars,coins,ts) values(?,?,?,?,?)', (charge, uid, stars, coins, now()))
        log(uid, 'dep', f'Пополнение {stars} ⭐' + (f' (бонус +{bonus}%)' if bonus else ''), coins)
    notify(uid, f'✅ Пополнение {stars} ⭐ → +{coins} монет')


def handle_update(up):
    try:
        if 'pre_checkout_query' in up:
            q = up['pre_checkout_query']
            ok = q.get('currency') == 'XTR' and str(q.get('invoice_payload', '')).startswith(f'dep:{q["from"]["id"]}:')
            tg('answerPreCheckoutQuery', pre_checkout_query_id=q['id'], ok=ok, **({} if ok else {'error_message': 'Платёж отклонён'}))
        m = up.get('message') or {}
        if m.get('successful_payment'):
            credit_payment(m['from']['id'], m['successful_payment'])
        elif (m.get('text') or '').startswith('/start'):
            kb = {'inline_keyboard': [[{'text': '🎰 Играть', 'web_app': {'url': PUBLIC_URL}}]]} if PUBLIC_URL.startswith('https') else None
            notify(m['chat']['id'], '🧠 Brainrot Vault — открывай кейсы, делай апгрейды и выводи брейнротов в Roblox!',
                   **({'reply_markup': kb} if kb else {}))
        elif (m.get('text') or '').startswith('/paysupport'):
            notify(m['chat']['id'], 'По вопросам оплаты пиши владельцу: @' + OWNER_USERNAME)
    except Exception:
        traceback.print_exc()


def bot_setup():
    if not BOT_TOKEN:
        print('⚠️  BOT_TOKEN не задан — оплата и бот отключены (игра работает только в DEV_MODE).')
        return
    try:
        print('Бот:', '@' + tg('getMe')['username'])
        if PUBLIC_URL.startswith('https'):
            tg('setWebhook', url=f'{PUBLIC_URL}/tg/{WEBHOOK_SECRET}', secret_token=WEBHOOK_SECRET,
               allowed_updates=['message', 'pre_checkout_query'])
            tg('setChatMenuButton', menu_button={'type': 'web_app', 'text': 'Играть', 'web_app': {'url': PUBLIC_URL}})
            print('Webhook установлен:', PUBLIC_URL)
        else:
            threading.Thread(target=poll, daemon=True).start()
            print('PUBLIC_URL не задан — работаю через long polling (локальный режим).')
    except Exception as e:
        print('bot_setup:', e)


def poll():
    off = 0
    try:
        tg('deleteWebhook')
    except Exception:
        pass
    while True:
        try:
            for up in tg('getUpdates', offset=off, timeout=25, allowed_updates=['message', 'pre_checkout_query']):
                off = up['update_id'] + 1
                handle_update(up)
        except Exception as e:
            print('poll:', e)
            time.sleep(3)


# ───────────────────────── ПРОМОКОДЫ, РОЛИ, АДМИН-МЕНЮ ─────────────────────────
def need(U, minrole):
    r = role_of(U['id'])
    if r < minrole:
        err('Нет доступа', 403)
    return r


def promo_status(p, used):
    if not p['active']:
        return 'off'
    if p['expires'] and p['expires'] < now():
        return 'expired'
    if p['max_act'] and used >= p['max_act']:
        return 'full'
    return 'ok'


def a_promo_create(U, b):
    role = need(U, 1)
    R = ROLES[role]
    kind = b.get('kind')
    code = (b.get('code') or '').strip().upper() or secrets.token_hex(3).upper()
    if not re.fullmatch(r'[A-Z0-9_]{3,24}', code):
        err('Код: 3–24 символа (A–Z, 0–9, _)')
    max_act, hours = int(b.get('max_act') or 0), float(b.get('hours') or 0)
    if role < 4:                                  # у ролей — жёсткие лимиты
        max_act = R['acts'] if not 0 < max_act <= R['acts'] else max_act
        hours = R['hours'] if not 0 < hours <= R['hours'] else hours
    value, case_id, qty = 0, None, 1
    if kind == 'deposit':
        value = int(b.get('value') or 0)
        if role < 4:
            value = R['dep'] if not 0 < value <= R['dep'] else value
        if not 1 <= value <= 1000:
            err('Бонус к депозиту: 1–1000 %')
    elif kind == 'coins':
        value = int(b.get('value') or 0)
        if not 1 <= value <= R['coins']:
            err(f'Монет в промо: 1–{R["coins"]}')
    elif kind == 'case':
        c = CASE.get(int(b.get('case', -1)))
        if not c or c['kind'] != 'paid':
            err('Выбери платный кейс')
        if c['price'] > R['case']:
            err(f'Для твоего уровня — кейсы до {R["case"]} монет')
        case_id, qty = c['id'], max(1, min(int(b.get('qty') or 1), 10 if role == 4 else 3))
    else:
        err('Тип промокода: coins / case / deposit')
    with tx():
        if DB.execute('select 1 from promos where code=?', (code,)).fetchone():
            err('Такой код уже существует')
        DB.execute('insert into promos(code,kind,value,case_id,qty,max_act,expires,creator,creator_name,created) values(?,?,?,?,?,?,?,?,?,?)',
                   (code, kind, value, case_id, qty, max_act, int(now() + hours * 3600) if hours > 0 else 0, U['id'], U.get('username') or str(U['id']), now()))
    return {'code': code, 'max_act': max_act, 'hours': hours}


def a_promos(U, b):
    role = need(U, 1)
    rows = DB.execute('select p.*,(select count(*) from promo_uses u where u.code=p.code) used from promos p ' +
                      ('' if role == 4 else 'where creator=? ') + 'order by created desc limit 100', () if role == 4 else (U['id'],)).fetchall()
    return {'list': [{'code': p['code'], 'kind': p['kind'], 'value': p['value'], 'case': CASE[p['case_id']]['name'] if p['case_id'] is not None else '',
                      'qty': p['qty'], 'max': p['max_act'], 'used': p['used'], 'exp': p['expires'], 'by': p['creator_name'],
                      'st': promo_status(p, p['used']), 'created': p['created']} for p in rows]}


def a_promo_toggle(U, b):
    role = need(U, 1)
    code = (b.get('code') or '').strip().upper()
    with tx():
        p = DB.execute('select creator from promos where code=?', (code,)).fetchone()
        if not p or (role < 4 and p['creator'] != U['id']):
            err('Промокод не найден')
        DB.execute('update promos set active=? where code=?', (1 if b.get('on') else 0, code))
    return {}


def a_promo_uses(U, b):
    role = need(U, 1)
    code = (b.get('code') or '').strip().upper()
    p = DB.execute('select creator from promos where code=?', (code,)).fetchone()
    if not p or (role < 4 and p['creator'] != U['id']):
        err('Промокод не найден')
    return {'list': [{'u': r['uname'] or r['user_id'], 't': r['ts']} for r in
                     DB.execute('select * from promo_uses where code=? order by id desc limit 100', (code,))]}


def a_staff(U, b):
    need(U, 4)
    out = []
    for s in DB.execute('select * from staff order by role desc, granted'):
        uid = s['user_id']
        st = {'un': s['username'], 'role': s['role'], 'rname': ROLES[s['role']]['name'], 'seen': uid is not None, 'promos': 0, 'acts': 0, 'users': 0, 'last': 0, 'recent': []}
        if uid:
            st['promos'] = DB.execute('select count(*) from promos where creator=?', (uid,)).fetchone()[0]
            r = DB.execute('select count(*),count(distinct u.user_id),max(u.ts) from promo_uses u join promos p on p.code=u.code where p.creator=?', (uid,)).fetchone()
            st['acts'], st['users'], st['last'] = r[0], r[1], r[2] or 0
            st['recent'] = [{'code': x['code'], 'u': x['uname'] or x['user_id'], 't': x['ts']} for x in DB.execute(
                'select u.* from promo_uses u join promos p on p.code=u.code where p.creator=? order by u.id desc limit 8', (uid,))]
        out.append(st)
    return {'list': out}


def a_role(U, b):
    need(U, 4)
    un = (b.get('username') or '').strip().lstrip('@').lower()
    role = int(b.get('role', 0))
    if not re.fullmatch(r'[a-z0-9_]{4,32}', un):
        err('Укажи Telegram-username')
    if un == OWNER_USERNAME:
        err('Владельцу роль выдавать не нужно')
    if role not in (0, 1, 2, 3):
        err('Уровень: 1 Блогер, 2 Помощник, 3 Партнёр, 0 — снять')
    with tx():
        if role == 0:
            DB.execute('delete from staff where username=?', (un,))
        else:
            u = DB.execute('select id from users where lower(username)=?', (un,)).fetchone()
            DB.execute('insert into staff(username,user_id,role,granted) values(?,?,?,?) on conflict(username) do update set role=?',
                       (un, u['id'] if u else None, role, now(), role))
    return {}


def a_wd_list(U, b):
    need(U, 4)
    return {'list': [{'id': r['id'], 'uid': r['user_id'], 'tg': r['tg'], 'nick': r['roblox'], 'item': r['item'], 'price': r['price'],
                      'st': r['status'], 't': r['created'], 'note': r['note']} for r in
                     DB.execute("select * from withdrawals order by (status='pending') desc, id desc limit 60")]}


def a_wd_resolve(U, b):
    need(U, 4)
    with tx():
        w = DB.execute('select * from withdrawals where id=?', (int(b.get('id', 0)),)).fetchone()
        if not w or w['status'] != 'pending':
            err('Заявка не найдена или уже обработана')
        ok = bool(b.get('ok'))
        DB.execute('update withdrawals set status=?,resolved=?,note=? where id=?', ('done' if ok else 'rejected', now(), (b.get('note') or '')[:200], w['id']))
        if not ok:
            DB.execute('insert into inv(user_id,item,ts) values(?,?,?)', (w['user_id'], w['item'], now()))
            log(w['user_id'], 'wd', f'Заявка #{w["id"]} отклонена, брейнрот возвращён', 0)
        else:
            log(w['user_id'], 'wd', f'Заявка #{w["id"]} выполнена: {ITEMS[w["item"]]["n"]} выдан', 0)
    notify(w['user_id'], (f'✅ Вывод #{w["id"]} выполнен: {ITEMS[w["item"]]["n"]} выдан на ник {w["roblox"]}.' if ok else
                          f'❌ Заявка #{w["id"]} отклонена, брейнрот вернулся в инвентарь. {b.get("note") or ""}'))
    return {}


def a_settings(U, b):
    need(U, 4)
    if b.get('set'):
        with tx():
            for k, v in b['set'].items():
                if k in DEFAULTS:
                    DB.execute('insert or replace into settings(key,value) values(?,?)', (k, str(max(0, int(v)))))
    return {'v': {k: setting(k) for k in DEFAULTS}}


def a_give(U, b):
    need(U, 4)
    un = (b.get('username') or '').strip().lstrip('@').lower()
    amt = int(b.get('amount', 0))
    with tx():
        u = DB.execute('select id from users where lower(username)=?', (un,)).fetchone()
        if not u:
            err('Пользователь не найден (он должен хотя бы раз открыть бота)')
        add_bal(u['id'], amt)
        log(u['id'], 'bonus', 'Выдано владельцем', amt)
    return {}


def a_overview(U, b):
    need(U, 4)
    q = lambda s: DB.execute(s).fetchone()[0] or 0
    return {'users': q('select count(*) from users'), 'stars': q('select sum(stars) from payments'), 'pay': q('select count(*) from payments'),
            'wd': q("select count(*) from withdrawals where status='pending'"), 'coins': q('select sum(balance) from users')}


API = {'state': a_state, 'cases': a_cases, 'open': a_open, 'sell': a_sell, 'buy': a_buy, 'upgrade': a_upgrade, 'withdraw': a_withdraw,
       'bonus': a_bonus, 'promo': a_promo, 'deposit': a_deposit, 'admin/promo/create': a_promo_create, 'admin/promos': a_promos,
       'admin/promo/toggle': a_promo_toggle, 'admin/promo/uses': a_promo_uses, 'admin/staff': a_staff, 'admin/role': a_role,
       'admin/wd': a_wd_list, 'admin/wd/resolve': a_wd_resolve, 'admin/settings': a_settings, 'admin/give': a_give, 'admin/overview': a_overview}


# ───────────────────────── HTTP-СЕРВЕР ─────────────────────────
def authenticate(h):
    u = None
    init = h.headers.get('X-Init-Data', '')
    if init and BOT_TOKEN:
        u = check_init_data(init)
    if not u and DEV_MODE and h.headers.get('X-Dev-User'):
        p = h.headers['X-Dev-User'].split(':')
        u = {'id': int(p[0]), 'username': p[1] if len(p) > 1 else '', 'first_name': p[2] if len(p) > 2 else 'Dev'}
    if not u:
        err('Открой игру через Telegram-бота', 401)
    upsert_user(u)
    return u


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def send(self, code, body, ctype='application/json; charset=utf-8', cache='no-store'):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', cache)
        self.end_headers()
        self.wfile.write(body)

    def static(self, rel):
        f = (STATIC / rel).resolve()
        if STATIC not in f.parents and f != STATIC / 'index.html' or not f.is_file():
            return self.send(404, {'error': 'not found'})
        ct = mimetypes.guess_type(str(f))[0] or 'application/octet-stream'
        img = f.suffix in ('.webp', '.png', '.jpg')
        self.send(200, f.read_bytes(), ct + ('; charset=utf-8' if ct.startswith('text') or 'javascript' in ct or 'json' in ct else ''),
                  'public, max-age=86400' if img else 'no-cache')

    def api(self, name, body):
        fn = API.get(name)
        if not fn:
            return self.send(404, {'error': 'not found'})
        try:
            U = authenticate(self) if name != 'cases' else None
            self.send(200, fn(U, body))
        except ApiError as e:
            self.send(e.code, {'error': str(e)})
        except Exception:
            traceback.print_exc()
            self.send(500, {'error': 'Ошибка сервера'})

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ('/', '/index.html'):
            return self.static('index.html')
        if path == '/healthz':
            return self.send(200, {'ok': True})
        if path.startswith('/static/'):
            return self.static(urllib.parse.unquote(path[8:]))
        if path.startswith('/api/'):
            return self.api(path[5:], {})
        self.send(404, {'error': 'not found'})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        n = int(self.headers.get('Content-Length') or 0)
        if n > 65536:
            return self.send(413, {'error': 'too big'})
        raw = self.rfile.read(n) if n else b''
        try:
            body = json.loads(raw or b'{}')
        except Exception:
            return self.send(400, {'error': 'bad json'})
        if path == f'/tg/{WEBHOOK_SECRET}':
            if self.headers.get('X-Telegram-Bot-Api-Secret-Token') != WEBHOOK_SECRET:
                return self.send(403, {'error': 'forbidden'})
            handle_update(body)
            return self.send(200, {'ok': True})
        if path.startswith('/api/'):
            return self.api(path[5:], body)
        self.send(404, {'error': 'not found'})


CASES_PAYLOAD = {}


def main():
    global CASES_PAYLOAD
    db_init()
    build_cases()
    CASES_PAYLOAD = cases_payload()
    threading.Thread(target=bot_setup, daemon=True).start()   # не задерживаем запуск сервера
    srv = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    srv.daemon_threads = True
    print(f'Сервер запущен: порт {PORT}, база {DB_PATH}' + (' [DEV_MODE]' if DEV_MODE else ''))
    srv.serve_forever()


if __name__ == '__main__':
    main()
