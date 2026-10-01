import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'words.db')
TXT_PATH = os.path.join(BASE_DIR, '我的词库.txt')


def parse_line(line):
    """
    支持两种格式：
      1) 制表符分隔：单词 \t 释义 \t 同义词（可省略）
      2) 空格分隔：  [序号] 单词 释义      <- 序号会被自动丢弃
    返回 (word, meaning, synonyms)
    """
    line = line.strip()
    if not line:
        return None

    # 1) 制表符格式
    if '\t' in line:
        parts = [p.strip() for p in line.split('\t')]
        word = parts[0]
        meaning = parts[1] if len(parts) > 1 else ''
        synonyms = parts[2] if len(parts) > 2 else ''
        if word.isdigit() and len(parts) > 1:      # 第一列其实是序号
            tokens = line.split(None, 2)
            if len(tokens) >= 3:
                word, meaning = tokens[1], tokens[2]
        return (word, meaning, synonyms) if word else None

    # 2) 空格格式（丢弃开头的序号）
    tokens = line.split(None, 2)
    if tokens and tokens[0].isdigit() and len(tokens) >= 3:
        tokens = tokens[1:]
    if len(tokens) >= 2:
        return tokens[0], tokens[1], ''
    return None


def import_from_txt():
    if not os.path.exists(TXT_PATH):
        print(f"找不到文件：{TXT_PATH}")
        return

    print("正在读取 txt 词库...")
    words_data = []
    with open(TXT_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            item = parse_line(line)
            if item:
                words_data.append(item)

    print(f"共读取到 {len(words_data)} 个词条，开始重建数据库...")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('DROP TABLE IF EXISTS words')
    c.execute('''CREATE TABLE words
                 (
                     id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                     word               TEXT NOT NULL,
                     meaning            TEXT NOT NULL,
                     word_score         INTEGER DEFAULT 0,
                     phrase_score       INTEGER DEFAULT 0,
                     word_done          INTEGER DEFAULT 0,
                     phrase_done        INTEGER DEFAULT 0,
                     essay_done         INTEGER DEFAULT 0,
                     is_mastered        INTEGER DEFAULT 0,
                     first_learned_date TEXT,
                     synonyms           TEXT,
                     phrases            TEXT,
                     essay_sentence     TEXT,
                     source             TEXT DEFAULT 'word'
                 )''')

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

    c.execute('DROP TABLE IF EXISTS records')
    c.execute('''CREATE TABLE records
                 (
                     id        INTEGER PRIMARY KEY AUTOINCREMENT,
                     word_id   INTEGER,
                     action    TEXT,
                     timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                 )''')

    insert_data = [(w, m, 0, 0, 0, 0, 0, 0, None, s) for w, m, s in words_data]
    c.executemany('''INSERT INTO words
                     (word, meaning, word_score, phrase_score, word_done,
                      phrase_done, essay_done, is_mastered, first_learned_date, synonyms)
                     VALUES (?,?,?,?,?,?,?,?,?,?)''', insert_data)

    conn.commit()
    conn.close()
    print(f"导入完成！共 {len(words_data)} 条，数据库已切换为「双积分模块 + 一键熟词」结构。")


if __name__ == '__main__':
    import_from_txt()
