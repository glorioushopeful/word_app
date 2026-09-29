import os
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request

app = Flask(__name__, template_folder='templates', static_folder='static', static_url_path='/static')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'words.db')


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/get_word')
def get_word():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 只抽“下次复习时间 <= 当前时间”的单词
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute('''SELECT id, word, meaning
                 FROM words
                 WHERE next_review_time <= ?
                 ORDER BY next_review_time ASC LIMIT 1''', (now_str,))
    row = c.fetchone()
    conn.close()

    if row:
        return jsonify({'id': row[0], 'word': row[1], 'meaning': row[2]})
    else:
        return jsonify({'id': None, 'word': '今日复习任务已完成', 'meaning': '所有到期的单词都背完了，休息一下吧！'})


@app.route('/submit', methods=['POST'])
def submit():
    data = request.get_json()
    word_id = data.get('id')
    action = data.get('action')

    if word_id is None:
        return jsonify({'status': 'ok', 'message': '已完成所有单词'})

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if action == 'know':
        # 查询当前熟悉度
        c.execute('SELECT familiarity FROM words WHERE id = ?', (word_id,))
        current_fam = c.fetchone()[0]
        new_fam = current_fam + 1

        # 根据熟悉度决定下次复习的时间间隔
        if new_fam == 1:
            interval = timedelta(days=1)
        elif new_fam == 2:
            interval = timedelta(days=2)
        elif new_fam == 3:
            interval = timedelta(days=4)
        elif new_fam == 4:
            interval = timedelta(days=7)
        else:
            interval = timedelta(days=15)

        next_time = (datetime.now() + interval).strftime('%Y-%m-%d %H:%M:%S')

        c.execute('UPDATE words SET familiarity = ?, next_review_time = ? WHERE id = ?',
                  (new_fam, next_time, word_id))
    else:
        # 不认识，熟悉度归 0，下次复习时间设为现在（马上重来）
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute('UPDATE words SET familiarity = 0, next_review_time = ? WHERE id = ?',
                  (now_str, word_id))

    # 记录操作
    c.execute('INSERT INTO records (word_id, action) VALUES (?, ?)', (word_id, action))

    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})


@app.route('/stats')
def stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM records WHERE DATE(timestamp) = DATE('now', 'localtime')")
    today_count = c.fetchone()[0]

    c.execute('SELECT COUNT(*) FROM words')
    total = c.fetchone()[0]

    # 已掌握定义为熟悉度 >= 3
    c.execute('SELECT COUNT(*) FROM words WHERE familiarity >= 3')
    mastered = c.fetchone()[0]

    conn.close()
    return jsonify({'today_count': today_count, 'total': total, 'mastered': mastered})


if __name__ == '__main__':
    app.run(debug=True)