"""Sul server italiano: mostra la struttura dei prezzari che il lettore unico non riconosce."""
import glob, io, zipfile, openpyxl
for f in glob.glob("/opt/garapronta/prezzari/Lombardia*.zip") + glob.glob("/opt/garapronta/prezzari/Abruzzo*.zip"):
    z = zipfile.ZipFile(f)
    print("\n##", f, z.namelist()[:20])
    for n in z.namelist():
        if n.lower().endswith(".xlsx") and "analisi" not in n.lower():
            wb = openpyxl.load_workbook(io.BytesIO(z.read(n)), read_only=True, data_only=True)
            for ws in wb.worksheets[:2]:
                print(" --", n[-70:], "|", ws.title, ws.max_row)
                for i, r in enumerate(ws.iter_rows(values_only=True)):
                    if 8 <= i <= 22:
                        print("     ", [str(x)[:35] for x in r[:12]])
                    if i > 22:
                        break
            break
