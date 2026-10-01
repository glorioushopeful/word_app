import os
import re
import sqlite3
import difflib
from datetime import datetime
from flask import Flask, render_template, jsonify, request

app = Flask(__name__, template_folder='templates', static_folder='static', static_url_path='/static')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'words.db')

# ========== 规则常量 ==========
KNOW_DELTA = 40          # 认识 +40
UNKNOWN_DELTA = -10      # 不认识 -10
PASS_SCORE = 60          # 达标线：分数 >= 60 才算该模块达标
ESSAY_PASS = 0.98        # 作文拼写相似度达标线 98%
DEFAULT_DAILY_NEW = 30   # 默认每日新词数
REVIEW_RATIO = 2         # 旧词复习量 = 每日新词数 × 2


def today_str():
    return datetime.now().strftime('%Y-%m-%d')


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """建表 + 自动迁移旧库（幂等）"""
    conn = get_conn()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS words
                 (
                     id                INTEGER PRIMARY KEY AUTOINCREMENT,
                     word              TEXT NOT NULL,
                     meaning           TEXT NOT NULL,
                     word_score        INTEGER DEFAULT 0,
                     phrase_score      INTEGER DEFAULT 0,
                     word_done         INTEGER DEFAULT 0,
                     phrase_done       INTEGER DEFAULT 0,
                     essay_done        INTEGER DEFAULT 0,
                     is_mastered       INTEGER DEFAULT 0,
                     first_learned_date TEXT,
                     synonyms          TEXT
                 )''')

    # 每日记录：同一天、同一个词、同一个模式只记一次
    c.execute('DROP TABLE IF EXISTS daily_review')
    c.execute('''CREATE TABLE daily_review
                 (
                     id          INTEGER PRIMARY KEY AUTOINCREMENT,
                     word_id     INTEGER NOT NULL,
                     review_date TEXT NOT NULL,
                     mode        TEXT DEFAULT 'word',
                     is_new      INTEGER DEFAULT 0,
                     UNIQUE (word_id, review_date, mode)
                 )''')

    c.execute('''CREATE TABLE IF NOT EXISTS records
                 (
                     id        INTEGER PRIMARY KEY AUTOINCREMENT,
                     word_id   INTEGER,
                     action    TEXT,
                     timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                 )''')

    # ---- 旧库补字段 ----
    c.execute('PRAGMA table_info(words)')
    cols = {row[1] for row in c.fetchall()}
    for name, ddl in (
        ('word_score', 'ALTER TABLE words ADD COLUMN word_score INTEGER DEFAULT 0'),
        ('phrase_score', 'ALTER TABLE words ADD COLUMN phrase_score INTEGER DEFAULT 0'),
        ('word_done', 'ALTER TABLE words ADD COLUMN word_done INTEGER DEFAULT 0'),
        ('phrase_done', 'ALTER TABLE words ADD COLUMN phrase_done INTEGER DEFAULT 0'),
        ('essay_done', 'ALTER TABLE words ADD COLUMN essay_done INTEGER DEFAULT 0'),
        ('is_mastered', 'ALTER TABLE words ADD COLUMN is_mastered INTEGER DEFAULT 0'),
        ('synonyms', 'ALTER TABLE words ADD COLUMN synonyms TEXT'),
        ('phrases', 'ALTER TABLE words ADD COLUMN phrases TEXT'),
        ('essay_sentence', 'ALTER TABLE words ADD COLUMN essay_sentence TEXT'),
        ('source', "ALTER TABLE words ADD COLUMN source TEXT DEFAULT 'word'"),
    ):
        if name not in cols:
            c.execute(ddl)

    if 'first_learned_date' not in cols:
        c.execute('ALTER TABLE words ADD COLUMN first_learned_date TEXT')

    # 老版本只有 score 字段时，把分数继承到单词模块
    if 'score' in cols:
        c.execute('UPDATE words SET word_score = score '
                  'WHERE (word_score IS NULL OR word_score = 0) AND score IS NOT NULL AND score <> 0')

    for col in ('word_score', 'phrase_score', 'word_done', 'phrase_done',
                'essay_done', 'is_mastered'):
        c.execute(f'UPDATE words SET {col} = 0 WHERE {col} IS NULL')

    conn.commit()
    conn.close()


def today_progress(c, daily_new):
    """(今日新词数, 今日已复习的不同旧词数, 复习上限)"""
    today = today_str()
    c.execute('SELECT COUNT(*) FROM words WHERE first_learned_date = ?', (today,))
    new_count = c.fetchone()[0]
    c.execute("""SELECT COUNT(DISTINCT word_id) FROM daily_review
                 WHERE review_date = ? AND mode IN ('word', 'phrase') AND is_new = 0""", (today,))
    review_count = c.fetchone()[0]
    return new_count, review_count, daily_new * REVIEW_RATIO


def blank_out(sentence, word):
    """把作文句子里的目标单词挖空"""
    if not sentence:
        return ''
    pat = re.compile(r'\b' + re.escape(word) + r'(?:s|es|ed|d|ing|ly)?\b', re.I)
    return pat.sub('________', sentence, count=1)


def item_dict(row):
    return {
        'id': row['id'],
        'word': row['word'],
        'meaning': row['meaning'],
        'synonyms': row['synonyms'] or '',
        'phrases': row['phrases'] or '',
        'essay_sentence': row['essay_sentence'] or '',
        'word_score': row['word_score'] or 0,
        'phrase_score': row['phrase_score'] or 0,
        'word_done': row['word_done'] or 0,
        'phrase_done': row['phrase_done'] or 0,
        'essay_done': row['essay_done'] or 0,
        'is_mastered': row['is_mastered'] or 0,
    }


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/get_item')
def get_item():
    mode = request.args.get('mode', 'word')
    if mode not in ('word', 'phrase', 'essay'):
        mode = 'word'
    try:
        daily_new = int(request.args.get('daily_new', DEFAULT_DAILY_NEW))
    except (TypeError, ValueError):
        daily_new = DEFAULT_DAILY_NEW
    daily_new = max(1, min(daily_new, 500))

    conn = get_conn()
    c = conn.cursor()
    today = today_str()
    new_count, review_count, review_limit = today_progress(c, daily_new)

    score_col = 'word_score' if mode == 'word' else 'phrase_score'
    done_col = 'word_done' if mode == 'word' else 'phrase_done'
    # 词组模式只推“有同义替换或写作搭配”的词条，两者都没有的直接跳过词组模块
    need_syn = (" AND (TRIM(COALESCE(synonyms, '')) <> '' "
                "OR TRIM(COALESCE(phrases, '')) <> '')") if mode == 'phrase' else ''

    row = None
    phase = None

    if mode == 'essay':
        # 优先推有作文例句的词条（有语境更好练），其次已学过的
        c.execute("""SELECT * FROM words
                     WHERE is_mastered = 0 AND essay_done = 0
                       AND COALESCE(essay_sentence, '') <> ''
                     ORDER BY (first_learned_date IS NULL), word_done DESC, id ASC
                     LIMIT 1""")
        row = c.fetchone()
        if row is None:
            # 没有带例句的词了，退回“直接拼写单词”，保证每个词条都能完成作文模块
            c.execute("""SELECT * FROM words
                         WHERE is_mastered = 0 AND essay_done = 0
                         ORDER BY (first_learned_date IS NULL), id ASC
                         LIMIT 1""")
            row = c.fetchone()
        phase = 'essay'

    else:
        new_left = daily_new - new_count
        review_left = review_limit - review_count
        # 新词:旧词 ≈ 1:2 交替推送（各自独立上限，不必先复习完）
        prefer_new = new_left > 0 and (review_left <= 0 or new_count * REVIEW_RATIO <= review_count)

        order = ['new', 'review'] if prefer_new else ['review', 'new']
        for kind in order:
            if kind == 'new':
                if new_left <= 0:
                    continue
                c.execute(f'''SELECT * FROM words
                             WHERE is_mastered = 0 AND first_learned_date IS NULL{need_syn}
                             ORDER BY id ASC LIMIT 1''')
                row = c.fetchone()
                if row:
                    c.execute('UPDATE words SET first_learned_date = ? WHERE id = ?', (today, row['id']))
                    conn.commit()
                    phase = 'new'
                    break
            else:
                if review_left <= 0:
                    continue
                c.execute(f'''SELECT * FROM words
                             WHERE is_mastered = 0 AND first_learned_date IS NOT NULL
                               AND {done_col} = 0{need_syn}
                               AND id NOT IN (SELECT word_id FROM daily_review
                                              WHERE review_date = ? AND mode IN ('word', 'phrase'))
                             ORDER BY {score_col} ASC, RANDOM()
                             LIMIT 1''', (today,))
                row = c.fetchone()
                if row:
                    phase = 'review'
                    break

    if row is None:
        conn.close()
        if mode == 'phrase':
            tip = ('暂无可练词组', '这些词条没有同义替换数据，已自动跳过词组模块')
        else:
            tip = ('今日任务已完成', '休息一下吧！')
        return jsonify({'id': None, 'word': tip[0], 'meaning': tip[1],
                        'phase': 'done', 'mode': mode,
                        'today_new': new_count, 'daily_new': daily_new,
                        'today_review': review_count, 'review_limit': review_limit})

    data = item_dict(row)
    if mode == 'essay' and data['essay_sentence']:
        data['sentence_blank'] = blank_out(data['essay_sentence'], data['word'])
    data.update({'phase': phase, 'mode': mode,
                 'today_new': new_count, 'daily_new': daily_new,
                 'today_review': review_count, 'review_limit': review_limit})
    conn.close()
    return jsonify(data)


@app.route('/submit', methods=['POST'])
def submit():
    data = request.get_json(silent=True) or {}
    word_id = data.get('id')
    action = data.get('action')

    rules = {
        'word_know': ('word_score', KNOW_DELTA, 'word_done'),
        'word_unknown': ('word_score', UNKNOWN_DELTA, None),
        'phrase_know': ('phrase_score', KNOW_DELTA, 'phrase_done'),
        'phrase_unknown': ('phrase_score', UNKNOWN_DELTA, None),
    }
    if word_id is None or action not in rules:
        return jsonify({'status': 'error', 'message': '参数不合法'})

    score_col, delta, done_col = rules[action]
    mode = 'word' if action.startswith('word') else 'phrase'

    conn = get_conn()
    c = conn.cursor()
    c.execute(f'SELECT {score_col}, first_learned_date FROM words WHERE id = ?', (word_id,))
    row = c.fetchone()
    if row is None:
        conn.close()
        return jsonify({'status': 'error', 'message': '词条不存在'})

    new_score = (row[0] or 0) + delta
    c.execute(f'UPDATE words SET {score_col} = ? WHERE id = ?', (new_score, word_id))

    # 达标只置位，不清除（分数跌破 60 也保留已达标状态）
    done = 0
    if done_col and new_score >= PASS_SCORE:
        c.execute(f'UPDATE words SET {done_col} = 1 WHERE id = ?', (word_id,))
        done = 1

    # 今日记录（新词 / 复习）
    today = today_str()
    c.execute('SELECT id FROM daily_review WHERE word_id = ? AND review_date = ?', (word_id, today))
    first_today = c.fetchone() is None
    c.execute('INSERT OR IGNORE INTO daily_review (word_id, review_date, mode, is_new) VALUES (?, ?, ?, ?)',
              (word_id, today, mode, 1 if (first_today and row['first_learned_date'] == today) else 0))

    c.execute('INSERT INTO records (word_id, action) VALUES (?, ?)', (word_id, action))
    conn.commit()
    conn.close()

    return jsonify({'status': 'ok', 'score': new_score, 'done': done,
                    'score_field': score_col, 'done_field': done_col or ''})


@app.route('/check_essay', methods=['POST'])
def check_essay():
    data = request.get_json(silent=True) or {}
    word_id = data.get('id')
    user_input = (data.get('input') or '').strip()
    reference = (data.get('reference') or '').strip()

    if word_id is None:
        return jsonify({'status': 'error', 'message': '缺少 id'})

    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT word, meaning, essay_done, essay_sentence FROM words WHERE id = ?', (word_id,))
    row = c.fetchone()
    if row is None:
        conn.close()
        return jsonify({'status': 'error', 'message': '词条不存在'})

    if not reference:
        reference = row['word']

    def normalize(s):
        return ' '.join(s.lower().split())

    ratio = difflib.SequenceMatcher(None, normalize(user_input), normalize(reference)).ratio()
    passed = ratio >= ESSAY_PASS

    if passed and not row['essay_done']:
        c.execute('UPDATE words SET essay_done = 1 WHERE id = ?', (word_id,))
        c.execute('INSERT INTO records (word_id, action) VALUES (?, ?)', (word_id, 'essay_pass'))
        conn.commit()

    conn.close()
    return jsonify({'status': 'ok',
                    'similarity': round(ratio * 100, 2),
                    'passed': passed,
                    'essay_done': 1 if (passed or row['essay_done']) else 0,
                    'reference': reference,
                    'sentence': row['essay_sentence'] or ''})


@app.route('/master', methods=['POST'])
def master():
    data = request.get_json(silent=True) or {}
    word_id = data.get('id')

    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT word_done, phrase_done, essay_done, synonyms, phrases FROM words WHERE id = ?',
              (word_id,))
    row = c.fetchone()
    if row is None:
        conn.close()
        return jsonify({'status': 'error', 'message': '词条不存在'})

    # 既无同义词又无写作搭配的词条，自动跳过词组模块，只要求单词 + 作文达标
    need_phrase = bool((row['synonyms'] or '').strip() or (row['phrases'] or '').strip())
    if not (row['word_done'] and row['essay_done'] and (row['phrase_done'] or not need_phrase)):
        conn.close()
        msg = '单词、词组、作文三个模块未全部达标' if need_phrase else '单词和作文两个模块未全部达标'
        return jsonify({'status': 'error', 'message': msg + '，还不能标记熟词'})

    c.execute('UPDATE words SET is_mastered = 1 WHERE id = ?', (word_id,))
    c.execute('INSERT INTO records (word_id, action) VALUES (?, ?)', (word_id, 'master'))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok', 'is_mastered': 1})


@app.route('/stats')
def stats():
    try:
        daily_new = int(request.args.get('daily_new', DEFAULT_DAILY_NEW))
    except (TypeError, ValueError):
        daily_new = DEFAULT_DAILY_NEW
    daily_new = max(1, min(daily_new, 500))

    conn = get_conn()
    c = conn.cursor()
    today = today_str()

    c.execute('SELECT COUNT(*) FROM words')
    total = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM words WHERE is_mastered = 1')
    mastered = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM words WHERE first_learned_date IS NOT NULL')
    learned = c.fetchone()[0]

    new_count, review_count, review_limit = today_progress(c, daily_new)
    c.execute('SELECT COUNT(*) FROM daily_review WHERE review_date = ?', (today,))
    today_count = c.fetchone()[0]

    # 三模块达标数 & 待一键熟词数
    c.execute('SELECT COUNT(*) FROM words WHERE word_done = 1')
    word_done = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM words WHERE phrase_done = 1')
    phrase_done = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM words WHERE essay_done = 1')
    essay_done = c.fetchone()[0]
    # 满足熟词条件但未标记（无同义词的词条不要求词组模块）
    c.execute("""SELECT COUNT(*) FROM words
                 WHERE word_done = 1 AND essay_done = 1 AND is_mastered = 0
                   AND (phrase_done = 1
                        OR (TRIM(COALESCE(synonyms, '')) = '' AND TRIM(COALESCE(phrases, '')) = ''))""")
    ready = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM words WHERE TRIM(COALESCE(synonyms, '')) = '' "
              "AND TRIM(COALESCE(phrases, '')) = ''")
    no_syn = c.fetchone()[0]

    conn.close()
    return jsonify({'total': total, 'mastered': mastered, 'learned': learned,
                    'today_count': today_count,
                    'today_new': new_count, 'daily_new': daily_new,
                    'today_review': review_count, 'review_limit': review_limit,
                    'word_done': word_done, 'phrase_done': phrase_done, 'essay_done': essay_done,
                    'ready': ready, 'no_syn': no_syn})


init_db()


def get_lan_ips():
    import socket
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith('127.') and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('223.5.5.5', 80))
        ip = s.getsockname()[0]
        if not ip.startswith('127.') and ip not in ips:
            ips.append(ip)
    except Exception:
        pass
    finally:
        s.close()
    return ips or ['127.0.0.1']


def find_free_port(start=5000, end=5100):
    """从 start 起找第一个空闲端口，避免和其他 Flask 项目抢 5000"""
    import socket as _sock
    for p in range(start, end):
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
        try:
            if s.connect_ex(('127.0.0.1', p)) != 0:
                return p
        finally:
            s.close()
    return start


if __name__ == '__main__':
    host = os.environ.get('HOST', '0.0.0.0')
    env_port = os.environ.get('PORT')
    # 指定端口就用指定的；否则自动避开被占用端口（如被茅台大屏项目占了 5000）
    port = int(env_port) if env_port else find_free_port()
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'

    print('=' * 56)
    print(f'  本机访问：  http://127.0.0.1:{port}')
    for ip in get_lan_ips():
        print(f'  手机访问：  http://{ip}:{port}   （连同一个 WiFi，逐个试）')
    print('  手机连不上？多半是校园网设备隔离，请双击「启动(外网穿透).bat」走免费隧道。')
    print('=' * 56)
    app.run(host=host, port=port, debug=debug, threaded=True)
