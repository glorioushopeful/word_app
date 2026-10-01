"""
从 PDF 里提取同义词 / 真题词组并写入 words.db
  - 考研英语同义词替换@空卡：按页面坐标分列解析「同义词分组」，组内互为同义，写入 words.synonyms
  - 英（一）/英（二）真题词组：解析「编号 短语 含义 例句」，作为独立词组词条导入
依赖：pip install pypdf
"""
import os
import re
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'words.db')

SYN_PDF = os.path.join(BASE_DIR, '考研英语同义词替换@空卡空卡空空卡(1).pdf')
PHRASE_PDFS = [
    os.path.join(BASE_DIR, '英（一）10-26年真题词组-背诵版(1)(1).pdf'),
    os.path.join(BASE_DIR, '英（二）10-26年真题词组-背诵版(1)(1).pdf'),
]

MAX_SYNONYMS = 5          # 每个词最多存几个同义词
CJK_SPACE = re.compile(r'(?<=[\u4e00-\u9fff，。；、（）“”])[ \t]+(?=[\u4e00-\u9fff])')


def page_items(page):
    items = []

    def visitor(text, cm, tm, fontDict, fontSize):
        if text.strip():
            items.append((float(tm[4]), float(tm[5]), text.strip()))
    page.extract_text(visitor_text=visitor)
    return items


def parse_synonym_groups(path):
    from pypdf import PdfReader
    reader = PdfReader(path)
    all_groups = []
    for page in reader.pages:
        rows = {}
        for x, y, t in page_items(page):
            if y < 60:
                continue
            rows.setdefault(round(y / 3), []).append((x, t))

        col_groups = [[], []]
        for key in sorted(rows, reverse=True):
            cells = sorted(rows[key])
            for ci, (lo, hi) in enumerate(((0, 250), (250, 600))):
                col = [t for x, t in cells if lo <= x < hi]
                if not col:
                    continue
                head = col[0]
                if re.search(r'[A-Za-z]', head):
                    if not col_groups[ci]:
                        col_groups[ci].append([])
                    col_groups[ci][-1].append(head.strip())
                elif re.fullmatch(r'[\u4e00-\u9fff；;、\s]*', head) and head.strip():
                    col_groups[ci].append([])
        for g in col_groups:
            all_groups.extend(g)
    return [g for g in all_groups if len(g) >= 2]


def parse_phrases(path):
    from pypdf import PdfReader
    reader = PdfReader(path)
    text = '\n'.join((p.extract_text() or '') for p in reader.pages)
    flat = re.sub(r'\s+', ' ', text)
    segs = re.split(r'(?<!\d)(\d{1,3})\s+(?=[A-Za-z])', flat)
    out = []
    for i in range(1, len(segs) - 1, 2):
        seg = re.sub(r'公众号.*?(?:背诵版|真题词组)', '', segs[i + 1])
        m = re.match(r'^([A-Za-z][A-Za-z\.\-\'() ]*?)\s*([\u4e00-\u9fff][^A-Za-z]*)', seg)
        if not m:
            continue
        phrase = m.group(1).strip()
        meaning = CJK_SPACE.sub('', m.group(2)).strip(' 。，,')
        if phrase and meaning and len(phrase) > 2:
            out.append((phrase, meaning))
    return out


def norm(w):
    """归一化：小写、去多余空格、去括号注解"""
    w = re.sub(r'\s+', ' ', (w or '').strip().lower())
    w = re.sub(r'\s*\([^)]*\)', '', w).strip()
    return w


def update_synonyms():
    if not os.path.exists(SYN_PDF):
        print('未找到同义词 PDF，跳过')
        return 0, 0

    groups = parse_synonym_groups(SYN_PDF)
    print(f'同义词 PDF：解析到 {len(groups)} 组 / {sum(len(g) for g in groups)} 词')

    # word -> 同义词集合（一个词可能出现在多组，合并）
    mapping = {}
    for g in groups:
        keys = [norm(w) for w in g]
        for i, k in enumerate(keys):
            if not k:
                continue
            others = [g[j] for j in range(len(g)) if j != i]
            mapping.setdefault(k, [])
            for o in others:
                if o not in mapping[k]:
                    mapping[k].append(o)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('PRAGMA table_info(words)')
    cols = {r[1] for r in c.fetchall()}
    if 'synonyms' not in cols:
        c.execute('ALTER TABLE words ADD COLUMN synonyms TEXT')

    c.execute('SELECT id, word FROM words')
    rows = c.fetchall()
    hit = 0
    for wid, word in rows:
        syn = mapping.get(norm(word))
        if not syn:
            continue
        c.execute('UPDATE words SET synonyms = ? WHERE id = ?',
                  ('；'.join(syn[:MAX_SYNONYMS]), wid))
        hit += 1
    conn.commit()

    c.execute("SELECT COUNT(*) FROM words WHERE synonyms IS NOT NULL AND TRIM(synonyms) <> ''")
    total_syn = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM words')
    total = c.fetchone()[0]
    conn.close()
    print(f'已为 {hit} 个词条写入同义词；词库覆盖 {total_syn}/{total}')
    return hit, total


def import_phrases():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('PRAGMA table_info(words)')
    cols = {r[1] for r in c.fetchall()}
    if 'source' not in cols:
        c.execute("ALTER TABLE words ADD COLUMN source TEXT DEFAULT 'word'")

    c.execute('SELECT word FROM words')
    exist = {norm(r[0]) for r in c.fetchall()}

    added, dup = 0, 0
    for path in PHRASE_PDFS:
        if not os.path.exists(path):
            print('未找到', os.path.basename(path))
            continue
        phrases = parse_phrases(path)
        print(f'{os.path.basename(path)}：解析到 {len(phrases)} 条词组')
        for phrase, meaning in phrases:
            k = norm(phrase)
            if not k or k in exist:
                dup += 1
                continue
            exist.add(k)
            c.execute('''INSERT INTO words (word, meaning, word_score, phrase_score,
                         word_done, phrase_done, essay_done, is_mastered,
                         first_learned_date, synonyms, source)
                         VALUES (?,?,0,0,0,0,0,0,NULL,'','phrase')''', (phrase, meaning))
            added += 1
    conn.commit()
    c.execute('SELECT COUNT(*) FROM words')
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM words WHERE source = 'phrase'")
    phrase_total = c.fetchone()[0]
    conn.close()
    print(f'新增词组 {added} 条（跳过重复/已存在 {dup} 条）；词库现有 {total} 条，其中词组 {phrase_total} 条')
    return added


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'phrases':
        import_phrases()
    elif len(sys.argv) > 1 and sys.argv[1] == 'synonyms':
        update_synonyms()
    else:
        update_synonyms()
        import_phrases()
        print('\n完成：python extract_pdf.py [synonyms|phrases] 可单独执行某一步')
