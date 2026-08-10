import sys
import argparse

import auth
import sharing


def _find(email: str) -> dict:
    user = auth.get_user_by_email(email)
    if not user:
        print(f"Errore: nessun utente con email {email}")
        sys.exit(1)
    return user


def cmd_list(args):
    users = auth.list_users(auth.ROLE_DEVELOPER)
    if not users:
        print("Nessun utente registrato.")
        return
    print(f"{'ID':<4} {'EMAIL':<30} {'RUOLO':<11} {'AZIENDA':<16} {'ATTIVO':<7} {'BLOCCATO'}")
    print("-" * 84)
    for u in users:
        print(f"{u['id']:<4} {u['email']:<30} {u['role']:<11} "
              f"{(u['azienda'] or '-'):<16} {('si' if u['active'] else 'no'):<7} "
              f"{('si' if u.get('locked') else 'no')}")


def cmd_create(args):
    try:
        u = auth.create_user(args.email, args.username, args.password,
                             role=args.role, azienda=args.azienda,
                             must_change_pw=args.temp)
        print(f"Utente creato: id={u['id']} email={u['email']} ruolo={u['role']}")
        if args.temp:
            print("La password e' temporanea: l'utente dovra' cambiarla al primo accesso.")
    except ValueError as e:
        print(f"Errore: {e}")
        sys.exit(1)


def cmd_reset_password(args):
    user = _find(args.email)
    try:
        auth.reset_password(user["id"], args.password)
        print(f"Password reimpostata per {args.email}.")
        print("L'utente dovra' cambiarla al primo accesso.")
    except ValueError as e:
        print(f"Errore: {e}")
        sys.exit(1)


def cmd_set_role(args):
    user = _find(args.email)
    try:
        auth.set_user_role(user["id"], args.role)
        print(f"Ruolo di {args.email} impostato a {args.role}.")
    except ValueError as e:
        print(f"Errore: {e}")
        sys.exit(1)


def cmd_activate(args):
    user = _find(args.email)
    auth.set_user_active(user["id"], True)
    print(f"Utente {args.email} attivato.")


def cmd_deactivate(args):
    user = _find(args.email)
    auth.set_user_active(user["id"], False)
    print(f"Utente {args.email} disattivato.")


def cmd_unlock(args):
    user = _find(args.email)
    auth.unlock_user(user["id"])
    print(f"Utente {args.email} sbloccato.")


def cmd_delete(args):
    user = _find(args.email)
    confirm = input(f"Confermi l'eliminazione di {args.email}? Le sue condivisioni e i suoi "
                    f"gruppi verranno rimossi. I documenti verranno riassegnati al developer "
                    f"al prossimo avvio del server. Scrivi 'ELIMINA' per procedere: ")
    if confirm.strip() != "ELIMINA":
        print("Operazione annullata.")
        return
    uid = user["id"]
    auth.delete_user(uid)
    purged = sharing.purge_user(uid)
    print(f"Utente {args.email} eliminato.")
    print(f"  condivisioni concesse rimosse:  {purged['shares_granted']}")
    print(f"  condivisioni ricevute rimosse:  {purged['shares_received']}")
    print(f"  gruppi rimossi:                 {purged['groups']}")
    print(f"  collocazioni personali rimosse: {purged['placements']}")


def cmd_promote_developer(args):
    user = _find(args.email)
    auth.set_user_role(user["id"], auth.ROLE_DEVELOPER)
    auth.set_user_active(user["id"], True)
    auth.unlock_user(user["id"])
    print(f"{args.email} e' ora developer, attivo e sbloccato.")


def cmd_recover(args):
    import getpass
    key = getpass.getpass("Chiave di recupero (OBS_RECOVERY_KEY): ")
    pw1 = getpass.getpass("Nuova password temporanea (min 6 caratteri): ")
    pw2 = getpass.getpass("Ripeti la password: ")
    if pw1 != pw2:
        print("Le due password non coincidono. Nessuna modifica effettuata.")
        sys.exit(1)
    try:
        result = auth.recover_developer_password(args.email, pw1, key)
    except PermissionError as e:
        print(f"Accesso negato: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"Errore: {e}")
        sys.exit(1)
    print(f"Password reimpostata per {result['email']}.")
    print("Al prossimo accesso verra' chiesto di sceglierne una nuova.")


def main():
    auth.init_db()
    parser = argparse.ArgumentParser(description="OBS - amministrazione utenti da riga di comando")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)

    p = sub.add_parser("create")
    p.add_argument("email")
    p.add_argument("username")
    p.add_argument("password")
    p.add_argument("--role", default=auth.ROLE_USER,
                   choices=[auth.ROLE_USER, auth.ROLE_ADMIN, auth.ROLE_DEVELOPER])
    p.add_argument("--azienda", default="")
    p.add_argument("--temp", action="store_true",
                   help="forza il cambio password al primo accesso")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("reset-password")
    p.add_argument("email")
    p.add_argument("password")
    p.set_defaults(func=cmd_reset_password)

    p = sub.add_parser("set-role")
    p.add_argument("email")
    p.add_argument("role", choices=[auth.ROLE_USER, auth.ROLE_ADMIN, auth.ROLE_DEVELOPER])
    p.set_defaults(func=cmd_set_role)

    p = sub.add_parser("activate")
    p.add_argument("email")
    p.set_defaults(func=cmd_activate)

    p = sub.add_parser("deactivate")
    p.add_argument("email")
    p.set_defaults(func=cmd_deactivate)

    p = sub.add_parser("unlock")
    p.add_argument("email")
    p.set_defaults(func=cmd_unlock)

    p = sub.add_parser("delete")
    p.add_argument("email")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("promote-developer")
    p.add_argument("email")
    p.set_defaults(func=cmd_promote_developer)

    p = sub.add_parser("recover")
    p.add_argument("email")
    p.set_defaults(func=cmd_recover)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
