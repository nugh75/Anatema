"""
Export respondent data to CSV.

Per file Excel produce 2 CSV:
  - {file}_demografia.csv  : una riga per rispondente, colonne = domande demografiche
  - {file}_domande.csv     : formato long, una riga per (rispondente, domanda, risposta)

Heuristic demografia: column_name contiene una delle keyword DEMO_KEYWORDS.
Col 0 (sempre "codice di 6 caratteri...") è usato come codice rispondente.

Output: /app/backups/exports/
"""
import csv
import os
import re
from collections import defaultdict

from app import create_app
from models import ExcelFile, TextCell, CellAnnotation, Label

DEMO_PATTERNS = [
    r'\bet[àa]\b', r'\banni di servizio\b', r'\banzianit[àa]\b',
    r'\bsesso\b', r'\bgenere\b', r'\bgender\b',
    r'\btipo di scuola\b', r'\btipo scuola\b', r'\bgrado di scuola\b',
    r'\bordine scuola\b', r'\bistituto\b', r'\bclasse\b', r'\banno di corso\b',
    r'\bsede\b', r'\bcitt[àa]\b', r'\bprovincia\b', r'\bregione\b', r'\bcomune\b',
    r'\bdisciplina insegnata\b', r'\bmateria insegnata\b', r'\bmateria principale\b',
    r'\bruolo\b', r'\bqualifica\b',
    r'\btitolo di studio\b', r'\bcittadinanza\b', r'\bnazionalit[àa]\b',
    r'\bresidenza\b', r'\bdata di nascita\b', r'\banno di nascita\b',
]
DEMO_MAX_LEN = 80


def _compile_patterns():
    return [re.compile(p, re.IGNORECASE) for p in DEMO_PATTERNS]

_DEMO_REGEX = None

OUT_DIR = '/app/instance/exports'


def is_demo_column(name):
    global _DEMO_REGEX
    if not name:
        return False
    if len(name) > DEMO_MAX_LEN:
        return False
    if _DEMO_REGEX is None:
        _DEMO_REGEX = _compile_patterns()
    return any(r.search(name) for r in _DEMO_REGEX)


def is_code_column(name):
    if not name:
        return False
    low = name.lower()
    return 'codice' in low and '6 caratteri' in low


def safe_filename(name):
    base = os.path.splitext(name)[0]
    return re.sub(r'[^A-Za-z0-9._-]+', '_', base)


def export_file(f):
    cells = TextCell.query.filter_by(excel_file_id=f.id).all()

    # Map (sheet, row_index) → list of cells
    rows = defaultdict(list)
    for c in cells:
        rows[(c.sheet_name, c.row_index)].append(c)

    # Identify per sheet: code_col_index, demo column indexes, question column indexes
    sheet_cols = defaultdict(dict)  # sheet → col_index → column_name
    for c in cells:
        sheet_cols[c.sheet_name][c.column_index] = c.column_name

    sheet_code_col = {}
    sheet_demo_cols = {}     # sheet → [(col_index, col_name), ...]
    sheet_question_cols = {} # sheet → [(col_index, col_name), ...]
    for sheet, cols in sheet_cols.items():
        code_col = None
        demo = []
        quest = []
        for ci, cn in sorted(cols.items()):
            if is_code_column(cn):
                code_col = ci
            elif is_demo_column(cn):
                demo.append((ci, cn))
            else:
                quest.append((ci, cn))
        sheet_code_col[sheet] = code_col
        sheet_demo_cols[sheet] = demo
        sheet_question_cols[sheet] = quest

    # Build respondent_id per row: code from code_col, fallback row_index
    def respondent_code(sheet, row_index, row_cells):
        code_col = sheet_code_col.get(sheet)
        if code_col is not None:
            for c in row_cells:
                if c.column_index == code_col:
                    return c.text_content.strip()
        return f'{sheet}_row{row_index}'

    # Labels per cell (via CellAnnotation)
    def labels_for_cell(cell_id):
        q = (CellAnnotation.query
             .filter_by(text_cell_id=cell_id)
             .join(Label, CellAnnotation.label_id == Label.id)
             .all())
        return [a.label.name for a in q if a.label]

    os.makedirs(OUT_DIR, exist_ok=True)
    fname_base = safe_filename(f.original_filename)

    # --- Demografia CSV ---
    demo_path = os.path.join(OUT_DIR, f'{fname_base}_demografia.csv')
    all_demo_headers = []
    seen = set()
    for sheet, demos in sheet_demo_cols.items():
        for ci, cn in demos:
            key = (sheet, ci)
            if key not in seen:
                seen.add(key)
                all_demo_headers.append((sheet, ci, cn))

    demo_rows = []
    for (sheet, ri), row_cells in sorted(rows.items()):
        if ri == 0:
            continue
        code = respondent_code(sheet, ri, row_cells)
        if not code:
            continue
        by_col = {c.column_index: c.text_content for c in row_cells}
        rec = {'file': f.original_filename, 'sheet': sheet, 'codice_rispondente': code}
        has_demo = False
        for (dsheet, dci, dcn) in all_demo_headers:
            if dsheet != sheet:
                continue
            val = by_col.get(dci, '')
            rec[dcn] = val
            if val:
                has_demo = True
        # Include row anyway so respondent list is complete
        demo_rows.append(rec)

    with open(demo_path, 'w', newline='', encoding='utf-8') as fp:
        fields = ['file', 'sheet', 'codice_rispondente']
        for (dsheet, dci, dcn) in all_demo_headers:
            fields.append(dcn)
        w = csv.DictWriter(fp, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for r in demo_rows:
            w.writerow(r)
    print(f'  {demo_path}: {len(demo_rows)} rispondenti, {len(all_demo_headers)} colonne demo')

    # --- Domande CSV (long) ---
    q_path = os.path.join(OUT_DIR, f'{fname_base}_domande.csv')
    n_risposte = 0
    with open(q_path, 'w', newline='', encoding='utf-8') as fp:
        fields = ['file', 'sheet', 'codice_rispondente', 'col_index',
                  'domanda', 'risposta', 'etichette']
        w = csv.DictWriter(fp, fieldnames=fields)
        w.writeheader()
        for (sheet, ri), row_cells in sorted(rows.items()):
            if ri == 0:
                continue
            code = respondent_code(sheet, ri, row_cells)
            code_col = sheet_code_col.get(sheet)
            for c in sorted(row_cells, key=lambda x: x.column_index):
                if code_col is not None and c.column_index == code_col:
                    continue
                if any(c.column_index == dci for (dsheet, dci, _) in all_demo_headers if dsheet == sheet):
                    continue
                labels = labels_for_cell(c.id)
                w.writerow({
                    'file': f.original_filename,
                    'sheet': sheet,
                    'codice_rispondente': code,
                    'col_index': c.column_index,
                    'domanda': (c.column_name or '').strip(),
                    'risposta': c.text_content,
                    'etichette': '|'.join(labels),
                })
                n_risposte += 1
    print(f'  {q_path}: {n_risposte} risposte')


def main():
    app = create_app()
    with app.app_context():
        for f in ExcelFile.query.order_by(ExcelFile.id).all():
            print(f'=== {f.original_filename} (id={f.id}) ===')
            export_file(f)


if __name__ == '__main__':
    main()
