"""
对「扫描版 PDF」做 OCR，提取作文句子并入库（只补充还没有例句的词条）
依赖：pip install pymupdf rapidocr-onnxruntime
用法：
  python ocr_extract.py              只跑页数少的范文/模板类（推荐先试这个）
  python ocr_extract.py all          跑全部扫描版（904 页，约 70+ 分钟）
  python ocr_extract.py 大作文 小作文 只跑文件名包含这些关键字的
"""
import os
import re
import sys
import time
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'words.db')
SRC_DIR = os.path.join(BASE_DIR, '英语文件')

DPI = 200
MAX_SENTENCE_LEN = 200
CACHE_DIR = os.path.join(BASE_DIR, '.ocr_cache')   # 每份 PDF 的 OCR 结果，支持断点续跑

sys.path.insert(0, BASE_DIR)
from extract_writing import word_pattern, sentence_ok, CJK  # 复用匹配与过滤规则


def cache_path(name):
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]', '_', name)
    return os.path.join(CACHE_DIR, safe + '.txt')


def ocr_text(path, limit=None):
    import fitz
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    doc = fitz.open(path)
    pages = doc.page_count if limit is None else min(limit, doc.page_count)
    out = []
    for i in range(pages):
        pix = doc.load_page(i).get_pixmap(dpi=DPI)
        res, _ = ocr(pix.tobytes('png'))
        if res:
            out.append('\n'.join(r[1] for r in res))
    return '\n'.join(out)


def fix_ocr(text):
    """OCR 英文常见毛病：字母之间的点（gazes.reflectively）还原成空格"""
    text = re.sub(r'(?<=[A-Za-z])\.(?=[A-Za-z])', ' ', text)
    text = re.sub(r'(?<=[A-Za-z])\s{2,}(?=[A-Za-z])', ' ', text)
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)
    return text


def is_scanned(path):
    from pypdf import PdfReader
    try:
        txt = '\n'.join((p.extract_text() or '') for p in PdfReader(path).pages)
    except Exception:
        txt = ''
    return len(txt) <= 500


def sentences_from(text):
    sents = []
    for s in re.split(r'(?<=[.!?])\s+|\n+', text):
        s = ' '.join(s.split())
        if not (40 <= len(s) <= MAX_SENTENCE_LEN):
            continue
        if re.search(CJK, s):
            continue
        if not sentence_ok(s):
            continue
        sents.append(s)
    return sents


def update_db(sentences):
    """把句子补进还没有例句的词条（每次处理完一份就调用，进度实时生效）"""
    conn = sqlite3.connect(DB_PATH)
    if not sentences:
        total = conn.execute("SELECT COUNT(*) FROM words "
                             "WHERE COALESCE(essay_sentence,'') <> ''").fetchone()[0]
        conn.close()
        return 0, total
    c = conn.cursor()
    rows = c.execute("SELECT id, word FROM words WHERE COALESCE(essay_sentence,'') = ''").fetchall()
    hit = 0
    for wid, word in rows:
        if not word or not re.match(r'^[A-Za-z]', word):
            continue
        pat = word_pattern(word)
        ss = [s for s in sentences if pat.search(s)]
        if not ss:
            continue
        ss.sort(key=len)
        c.execute('UPDATE words SET essay_sentence = ? WHERE id = ?', (ss[0], wid))
        hit += 1
    conn.commit()
    c.execute("SELECT COUNT(*) FROM words WHERE COALESCE(essay_sentence,'') <> ''")
    total_have = c.fetchone()[0]
    conn.close()
    return hit, total_have


def collect(keywords=None, only_small=True, small_limit=10, max_pages=None):
    targets = []
    for name in sorted(os.listdir(SRC_DIR)):
        if not name.lower().endswith('.pdf'):
            continue
        path = os.path.join(SRC_DIR, name)
        if not is_scanned(path):
            continue
        import fitz
        try:
            n = fitz.open(path).page_count
        except Exception:
            continue
        if keywords and not any(k in name for k in keywords):
            continue
        if only_small and n > small_limit:
            continue
        targets.append((name, path, n))

    if not targets:
        print('没有符合条件的扫描版 PDF')
        return

    targets.sort(key=lambda x: x[2])      # 页数少的先跑，中断也有收益
    total_pages = sum(n for _, _, n in targets)
    done = [t for t in targets if os.path.exists(cache_path(t[0]))]
    print(f'待处理 {len(targets)} 份 / {total_pages} 页，预计 {total_pages * 5 / 60:.1f} 分钟')
    print(f'已有缓存（可跳过）: {len(done)} 份')

    new_sentences = []
    t0 = time.time()
    for idx, (name, path, n) in enumerate(targets, 1):
        cp = cache_path(name)
        if os.path.exists(cp):                       # 断点续跑
            with open(cp, encoding='utf-8') as f:
                text = f.read()
            print(f'  [{idx}/{len(targets)}] 用缓存  {name}')
        else:
            t = time.time()
            text = fix_ocr(ocr_text(path, limit=max_pages))
            with open(cp, 'w', encoding='utf-8') as f:
                f.write(text)
            print(f'  [{idx}/{len(targets)}] OCR完成 {name}: {n} 页 '
                  f'（{time.time() - t:.0f}s）', flush=True)

        sents = sentences_from(text)
        new_sentences.extend(sents)
        hit, total_have = update_db(sents)               # 每份处理完立即入库
        print(f'        本份 {len(sents)} 句 -> 补例句 {hit} 个，词库现有例句 {total_have}',
              flush=True)

    print(f'OCR 完成，用时 {(time.time() - t0) / 60:.1f} 分钟，共 {len(new_sentences)} 句')

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT id, word FROM words WHERE COALESCE(essay_sentence,'') = ''").fetchall()
    conn.close()
    if not rows:
        print('所有词条都已有例句')
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    hit = 0
    for wid, word in rows:
        if not word or not re.match(r'^[A-Za-z]', word):
            continue
        pat = word_pattern(word)
        ss = [s for s in new_sentences if pat.search(s)]
        if not ss:
            continue
        ss.sort(key=len)
        c.execute('UPDATE words SET essay_sentence = ? WHERE id = ?', (ss[0], wid))
        hit += 1
    conn.commit()
    c.execute("SELECT COUNT(*) FROM words WHERE COALESCE(essay_sentence,'') <> ''")
    total_have = c.fetchone()[0]
    conn.close()
    print(f'新增例句的词条：{hit} 个；词库现有例句词条：{total_have}')


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        collect(only_small=True, small_limit=10)          # 默认只跑页数少的
    elif args[0] == 'all':
        collect(only_small=False)
    else:
        collect(keywords=args, only_small=False)
