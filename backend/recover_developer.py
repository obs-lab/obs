import sys
import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))

import auth


def list_developers():
    conn = auth._connect()
    try:
        rows = conn.execute(
            "SELECT id, email, username, active FROM users WHERE role = ? ORDER BY id",
            (auth.ROLE_DEVELOPER,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def main():
    auth.init_db()
    devs = list_developers()

    if not devs:
        print("Nessun account developer trovato nel database.")
        print("Per crearne uno nuovo, imposta DEV_EMAIL e DEV_PASSWORD e riavvia,")
        print("oppure usa il comando ufficiale di recupero.")
        return

    print("Account developer presenti:")
    for d in devs:
        stato = "attivo" if d["active"] else "DISATTIVATO"
        print(f"  id={d['id']}  {d['email']}  ({d['username']})  [{stato}]")
    print("")

    target_email = input("Email del developer da recuperare: ").strip().lower()
    user = auth.get_user_by_email(target_email)

    if not user or user["role"] != auth.ROLE_DEVELOPER:
        print("Email non valida o non corrisponde a un developer.")
        return

    if not user["active"]:
        auth.set_user_active(user["id"], True)
        print("Account riattivato.")

    pw1 = getpass.getpass("Nuova password temporanea (min 6 caratteri): ")
    pw2 = getpass.getpass("Ripeti la password: ")

    if pw1 != pw2:
        print("Le due password non coincidono. Nessuna modifica effettuata.")
        return

    try:
        auth.reset_password(user["id"], pw1)
    except ValueError as e:
        print(f"Errore: {e}")
        return

    print("")
    print(f"Password reimpostata per {user['email']}.")
    print("Al prossimo login ti verra' chiesto di sceglierne una nuova.")


if __name__ == "__main__":
    main()
