import argparse
import socket
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import main as obs
import auth

SUPPORTED = {".pdf", ".txt", ".docx", ".doc", ".md", ".csv", ".xlsx", ".xls"}


def server_is_running(port=8000):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.4)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def resolve_owner(email):
    if not email:
        uid = auth.developer_user_id()
        if uid is None:
            sys.exit("Nessun account developer trovato. Indica un proprietario con --owner.")
        return uid
    u = auth.get_user_by_email(email)
    if not u:
        sys.exit("Utente non trovato: " + email)
    return u["id"]


def ensure_folder(name, owner_id, created):
    for f in obs._folders:
        if f.get("name", "").lower() == name.lower() and f.get("owner_id") == owner_id:
            return f["folder_id"]
    folder = {
        "folder_id": uuid.uuid4().hex[:10],
        "name": name[:100],
        "owner_id": owner_id,
        "created": datetime.utcnow().isoformat(),
    }
    obs._folders.append(folder)
    created.append(name)
    return folder["folder_id"]


def plan(root, default_azienda):
    items = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED:
            continue
        if path.name.startswith("."):
            continue
        rel = path.relative_to(root)
        parts = rel.parts[:-1]
        azienda = parts[0] if parts else (default_azienda or "")
        folder = parts[1] if len(parts) > 1 else (parts[0] if parts else None)
        items.append({"path": path, "azienda": azienda, "folder": folder})
    return items


def main():
    ap = argparse.ArgumentParser(
        description="Ingestione massiva di un albero di cartelle in OBS.")
    ap.add_argument("root", help="Cartella radice da ingerire")
    ap.add_argument("--owner", default=None, help="Email del proprietario dei documenti")
    ap.add_argument("--azienda", default=None,
                    help="Azienda per i file nella radice, se non ricavabile dalle cartelle")
    ap.add_argument("--settore", default="")
    ap.add_argument("--tipo", default="documento")
    ap.add_argument("--dry-run", action="store_true",
                    help="Mostra cosa verrebbe fatto senza scrivere nulla")
    ap.add_argument("--skip-existing", action="store_true",
                    help="Salta i file gia' presenti in archivio")
    ap.add_argument("--port", type=int, default=8000,
                    help="Porta su cui verificare che OBS non sia in esecuzione")
    ap.add_argument("--force", action="store_true",
                    help="Ignora il controllo sul server in esecuzione")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        sys.exit("Non e' una cartella: " + str(root))

    if server_is_running(args.port) and not args.force:
        sys.exit(
            "OBS sembra in esecuzione sulla porta %d.\n"
            "Questo script scrive direttamente sull'indice: se il server e' acceso,\n"
            "i due processi si sovrascriverebbero a vicenda e l'archivio si corromperebbe.\n"
            "Ferma OBS, poi rilancia. Riavvialo a ingestione conclusa.\n"
            "Usa --force solo se sai con certezza che nessun OBS sta girando." % args.port)

    obs._load_persisted_index()
    obs._load_folders()

    owner_id = resolve_owner(args.owner)
    items = plan(root, args.azienda)

    if not items:
        sys.exit("Nessun file supportato trovato sotto " + str(root))

    missing = [i for i in items if not i["azienda"]]
    if missing:
        sys.exit("%d file stanno nella radice e non hanno un'azienda. "
                 "Mettili in una sottocartella col nome dell'azienda, "
                 "oppure passa --azienda." % len(missing))

    known = {c.get("filename") for c in obs._chunk_store}

    print("Radice      : %s" % root)
    print("Proprietario: id %s" % owner_id)
    print("File trovati: %d" % len(items))
    print()
    for i in items:
        flag = ""
        if args.skip_existing and i["path"].name in known:
            flag = "  [gia' presente, salto]"
        print("  %-40s azienda=%-18s cartella=%s%s" % (
            i["path"].name[:40], i["azienda"], i["folder"] or "-", flag))

    if args.dry_run:
        print("\nDry run. Nessuna modifica scritta.")
        return

    print()
    if input("Procedo con l'ingestione? (scrivi SI) ").strip() != "SI":
        print("Annullato.")
        return

    created_folders = []
    ok = 0
    skipped = 0
    failed = []
    t0 = time.time()

    for n, i in enumerate(items, 1):
        name = i["path"].name
        if args.skip_existing and name in known:
            skipped += 1
            continue

        fid = ensure_folder(i["folder"], owner_id, created_folders) if i["folder"] else None
        dest = obs.DOCS_DIR / ("%s_%s" % (uuid.uuid4(), name))

        try:
            dest.write_bytes(i["path"].read_bytes())
            res = obs.ingest_document(
                filepath=dest,
                filename=name,
                azienda=i["azienda"],
                settore=args.settore,
                tipo=args.tipo,
                titolo=i["path"].stem,
                folder_id=fid,
                owner_id=owner_id,
            )
            if res.get("error"):
                failed.append((name, res["error"]))
                dest.unlink(missing_ok=True)
            else:
                ok += 1
                print("  [%d/%d] %s  (%d chunk)" % (n, len(items), name, res.get("chunks_added", 0)))
        except Exception as e:
            failed.append((name, str(e)[:80]))
            dest.unlink(missing_ok=True)

        if n % 25 == 0:
            obs._persist_index()
            obs._persist_folders()

    obs._persist_index()
    obs._persist_folders()

    dt = time.time() - t0
    print()
    print("Ingeriti     : %d" % ok)
    print("Saltati      : %d" % skipped)
    print("Falliti      : %d" % len(failed))
    print("Cartelle nuove: %d %s" % (len(created_folders), created_folders or ""))
    print("Tempo        : %.1f s" % dt)
    if failed:
        print()
        print("Errori:")
        for nm, err in failed:
            print("  %-40s %s" % (nm[:40], err))


if __name__ == "__main__":
    main()
