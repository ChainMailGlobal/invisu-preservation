"""compare_readers — the same 23 sheets read by two eyes, scored on the same metric.

Per sheet: entries, whether the sheet's own "SHEET N OF 22" number was read,
typed-reference lettering found, title, finish reason and latency (from the
read provenance each page carries). No ground truth is needed and no ranking
is claimed: it is the measured metric on this set, two columns.

Usage: python tools/compare_readers.py data/iolani-palace runs/tf_supervl
"""
import glob, json, os, re, sys


def rows(pdir):
    out = {}
    for f in sorted(glob.glob(os.path.join(pdir, '*.scene.json')), key=lambda p: int(os.path.basename(p).split('.')[0])):
        d = json.load(open(f, encoding='utf-8'))
        if d.get('kind') != 'sheet':
            continue
        pg = os.path.basename(f).split('.')[0]
        texts = [s[0] for s in d.get('spans') or []]
        r = d.get('read') or {}
        out[pg] = dict(n=len(texts),
                       selfno=any(re.search(r'SHEET\s*\w+\s*OF\s*\d+', t, re.I) for t in texts),
                       refs=sum(1 for t in texts if re.search(r'SEE\s+(DETAIL\s+)?SHEET', t, re.I)),
                       title=(d.get('title') or '')[:34], finish=r.get('finish'), sec=r.get('latency_s'),
                       model=(r.get('model') or '?').split('/')[-1][:28], provider=r.get('provider'))
    return out


def main(a, b):
    A, B = rows(a), rows(b)
    print(f"{'pg':>3} | {'A n':>4} {'self':>4} {'refs':>4} {'sec':>5} | {'B n':>4} {'self':>4} {'refs':>4} {'sec':>5} {'fin':<6} | titles agree")
    tot = dict(An=0, Bn=0, As=0, Bs=0, Ar=0, Br=0, agree=0, sheets=0)
    for pg in A:
        x, y = A[pg], B.get(pg, {})
        tot['sheets'] += 1; tot['An'] += x['n']; tot['Bn'] += y.get('n', 0)
        tot['As'] += x['selfno']; tot['Bs'] += bool(y.get('selfno')); tot['Ar'] += x['refs']; tot['Br'] += y.get('refs', 0)
        agree = bool(x['title']) and x['title'].upper() == (y.get('title') or '').upper()
        tot['agree'] += agree
        print(f"{pg:>3} | {x['n']:>4} {'y' if x['selfno'] else '-':>4} {x['refs']:>4} {str(x['sec']):>5} | "
              f"{y.get('n', 0):>4} {'y' if y.get('selfno') else '-':>4} {y.get('refs', 0):>4} {str(y.get('sec')):>5} {str(y.get('finish')):<6} | {'yes' if agree else 'no: ' + (y.get('title') or '')}")
    a_m = next(iter(A.values()))['model']; b_m = next((v['model'] for v in B.values() if v.get('model') != '?'), '?')
    print(f"\nA = {a_m} ({next(iter(A.values()))['provider']}): {tot['An']} entries, self-numbers {tot['As']}/{tot['sheets']}, ref lettering {tot['Ar']}")
    print(f"B = {b_m} ({next((v['provider'] for v in B.values() if v.get('provider')), '?')}): {tot['Bn']} entries, self-numbers {tot['Bs']}/{tot['sheets']}, ref lettering {tot['Br']}; titles agree on {tot['agree']}/{tot['sheets']}")


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
