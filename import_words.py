import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'words.db')
TXT_PATH = os.path.join(BASE_DIR, '我的词库.txt')


def import_from_txt():
    if not os.path.exists(TXT_PATH):
        print(f"❌ 找不到文件：{TXT_PATH}")
        return

    print("正在读取 txt 词库...")
    words_data = []
    with open(TXT_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # 按制表符或空格切分，取第一部分当单词，剩下的当释义
            parts = line.split('\t')
            if len(parts) >= 2:
                word = parts[0].strip()
                meaning = parts[1].strip()
            else:
                # 如果没有制表符，就按第一个空格切分
                parts = line.split(' ', 1)
                word = parts[0].strip()
                meaning = parts[1].strip() if len(parts) > 1 else ''

            if word:
                words_data.append((word, meaning))

    print(f"共读取到 {len(words_data)} 个单词，开始导入数据库...")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM words')  # 清空旧数据
    c.executemany('INSERT INTO words (word, meaning, familiarity) VALUES (?, ?, 0)', words_data)
    conn.commit()
    conn.close()
    print("✅ 导入完成！你的词库已经更新。")


if __name__ == '__main__':
    import_from_txt()