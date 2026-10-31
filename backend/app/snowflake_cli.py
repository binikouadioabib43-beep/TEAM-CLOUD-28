"""Outil technique Snowflake (aucune action dans l'interface).

Usage (depuis la racine du projet) :
  python -m backend.app.snowflake_cli init --account ORG-COMPTE --user MON_USER [--role ACCOUNTADMIN] [--warehouse COMPUTE_WH] [--cortex]
      -> cree la cle RSA, ecrit .env, affiche la commande ALTER USER a executer une fois dans Snowsight
  python -m backend.app.snowflake_cli check      -> diagnostic (connexion, region, Cortex)
  python -m backend.app.snowflake_cli setup      -> installe base, tables, vues et simulation GENERATOR (scripts 01, 02, 04, 06)
  python -m backend.app.snowflake_cli sync       -> copie les donnees de l'application vers Snowflake
  python -m backend.app.snowflake_cli test-ai    -> teste Cortex (texte et assistant)
  python -m backend.app.snowflake_cli all        -> check + setup + sync + test-ai
"""
import argparse
import re
import sys

from .config import settings


def _print_table(rows: list[dict]) -> None:
    for r in rows:
        print("   " + " | ".join(f"{k}={v}" for k, v in r.items()))


def cmd_init(args) -> None:
    from .config import save_env
    from .services.snowflake_client import KEY_FILE, ensure_keypair

    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", args.account) or not re.fullmatch(r"[A-Za-z0-9_.@\-]+", args.user):
        sys.exit("Identifiant de compte ou utilisateur invalide.")
    public_key = ensure_keypair()
    settings.update_snowflake({
        "account": args.account, "user": args.user, "role": args.role, "warehouse": args.warehouse,
        "database": "ECOABIDJAN", "schema": "CORE", "private_key_file": str(KEY_FILE),
        "password": None, "authenticator": None,
    })
    save_env({"AI_PROVIDER": "snowflake" if args.cortex else "local", "ASSISTANT_PROVIDER": "auto"})
    sql = f"ALTER USER \"{args.user.upper()}\" SET RSA_PUBLIC_KEY='{public_key}';"
    (settings.data_dir / "snowflake_alter_user.sql").write_text(sql + "\n", encoding="utf-8")
    print("Configuration ecrite dans .env (aucun mot de passe). Cle privee :", KEY_FILE)
    print("\nA executer UNE FOIS dans Snowsight (feuille SQL), puis lancer : python -m backend.app.snowflake_cli all\n")
    print(sql)


def cmd_check(_args) -> bool:
    from .services.snowflake_client import run_diagnostics

    print("Diagnostic Snowflake :")
    checks = run_diagnostics()
    for c in checks:
        print(f"  {'OK ' if c['ok'] else 'ERR'} {c['check']} : {c['detail']}")
    return checks[0]["ok"]


def cmd_setup(_args) -> None:
    from .services.snowflake_client import run_setup_scripts

    print("Installation (scripts 01, 02, 04, 06)…")
    r = run_setup_scripts()
    print("  Role :", r.get("role"))
    for s in r["scripts"]:
        print(f"  {s['script']} : {s['ok']} instructions OK, {len(s['erreurs'])} erreur(s)")
        for e in s["erreurs"][:5]:
            print("     -", e)
    print("  Controles :", ", ".join(f"{c['controle']}={c['valeur']}" for c in r["controles"]))
    print("  Synthese de la simulation Snowflake (schema SIM) :")
    _print_table(r["synthese"])


def cmd_sync(_args) -> None:
    from .database import Base, SessionLocal, engine
    from .services.snowflake_client import sync_to_snowflake

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        summary = sync_to_snowflake(db)
    print("Synchronisation vers ECOABIDJAN.CORE :")
    for table, n in summary.items():
        print(f"  {table:<22} {n:>7} lignes")


def cmd_test_ai(_args) -> None:
    from .services.assistant import cortex_reply, tariffs
    from .database import SessionLocal
    from .services.snowflake_client import connect

    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT AI_COMPLETE(%s, 'Dis bonjour en une phrase, en francais.')", (settings.cortex_model,))
        print("AI_COMPLETE :", cur.fetchone()[0])
    finally:
        conn.close()
    with SessionLocal() as db:
        reply = cortex_reply("Quels sont les tarifs de rachat ?", [], {"tarifs": tariffs(db)}, None)
    print("Assistant Eco via Cortex :", reply)


def main() -> None:
    p = argparse.ArgumentParser(prog="snowflake_cli", description="Outil technique Snowflake d'EcoAbidjan")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init", help="configurer la connexion par cle RSA")
    i.add_argument("--account", required=True, help="identifiant du compte, ex. ORGNAME-ACCOUNTNAME")
    i.add_argument("--user", required=True, help="nom d'utilisateur Snowflake")
    i.add_argument("--role", default="ACCOUNTADMIN")
    i.add_argument("--warehouse", default="COMPUTE_WH")
    i.add_argument("--cortex", action="store_true", help="analyser les photos avec Cortex AI")
    for name in ("check", "setup", "sync", "test-ai", "all"):
        sub.add_parser(name)
    args = p.parse_args()

    try:
        if args.cmd == "init":
            cmd_init(args)
        elif args.cmd == "check":
            cmd_check(args)
        elif args.cmd == "setup":
            cmd_setup(args)
        elif args.cmd == "sync":
            cmd_sync(args)
        elif args.cmd == "test-ai":
            cmd_test_ai(args)
        elif args.cmd == "all":
            if cmd_check(args):
                cmd_setup(args)
                cmd_sync(args)
                try:
                    cmd_test_ai(args)
                except Exception as exc:  # noqa: BLE001
                    print("Cortex indisponible :", exc)
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"Erreur : {exc}")


if __name__ == "__main__":
    main()
