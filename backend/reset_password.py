import sys
import getpass

import auth


def main():
    auth.init_db()

    print("OBS password reset")
    print("Resets the password for any account without needing the current one.")
    print("The user will be asked to set a new password at next login.")
    print("")

    email = input("Account email: ").strip().lower()
    if not email:
        print("No email provided. Nothing done.")
        sys.exit(1)

    user = auth.get_user_by_email(email)
    if not user:
        print(f"No account found for {email}.")
        sys.exit(1)

    print(f"Found: {user['email']} (role: {user['role']}, active: {bool(user['active'])})")
    print("")

    pw1 = getpass.getpass("New temporary password (min 6 characters): ")
    pw2 = getpass.getpass("Repeat the password: ")

    if pw1 != pw2:
        print("The two passwords do not match. Nothing done.")
        sys.exit(1)

    try:
        auth.reset_password(user["id"], pw1)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print("")
    print(f"Password reset for {user['email']}.")
    print("A permanent password will be requested at next login.")


if __name__ == "__main__":
    main()
