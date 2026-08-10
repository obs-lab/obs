import os
import sys
import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))

import auth


def main():
    auth.init_db()

    if not os.environ.get("OBS_RECOVERY_KEY", ""):
        print("Recupero disabilitato.")
        print("Imposta la chiave di recupero prima di usare questo comando:")
        print("  export OBS_RECOVERY_KEY=la-tua-chiave-segreta")
        print("La stessa chiave dovra' essere fornita durante il recupero.")
        return

    devs = auth.list_developers()
    if not devs:
        print("Nessun account developer presente nel database.")
        return

    print("Account developer presenti:")
    for d in devs:
        stato = "attivo" if d["active"] else "DISATTIVATO"
        print(f"  {d['email']}  ({d['username']})  [{stato}]")
    print("")

    email = input("Email del developer da recuperare: ").strip().lower()
    key = getpass.getpass("Chiave di recupero (OBS_RECOVERY_KEY): ")
    pw1 = getpass.getpass("Nuova password temporanea (min 6 caratteri): ")
    pw2 = getpass.getpass("Ripeti la password: ")

    if pw1 != pw2:
        print("Le due password non coincidono. Nessuna modifica effettuata.")
        return

    try:
        result = auth.recover_developer_password(email, pw1, key)
    except PermissionError as e:
        print(f"Accesso negato: {e}")
        return
    except ValueError as e:
        print(f"Errore: {e}")
        return

    print("")
    print(f"Password reimpostata per {result['email']}.")
    print("Al prossimo login ti verra' chiesto di sceglierne una nuova.")


if __name__ == "__main__":
    main()
