# -*- coding: utf-8 -*-


import os
import sys
import time
import subprocess
from typing import List, Optional

# ---------- KONFIG ----------
SITE_ROOT = r"c:\Users\Jakub\Downloads\__Eprojekty\www"
GITHUB_USER = "jakub-eubrand"
GITHUB_REPO = "poolabloom..github.io"  # repo user pages -> serwowane z branch main
BRANCH = "main"
CUSTOM_DOMAIN: Optional[str] = None  # np. "eubrand.pl" albo zostaw None
COMMIT_MESSAGE = "Automated deploy - static site push"
# ----------------------------

# Deklaratywny retry wrapper z obsługą port exhaustion (10048) i chwilowych błędów sieci
def run_cmd(cmd: List[str], cwd: Optional[str] = None, check: bool = True, max_retries: int = 6, base_sleep: float = 1.5):
    """
    Uruchamia polecenie w subprocess.run z retry.
    - Retry przy: CalledProcessError, OSError (w tym WinError 10048), chwilowe błędy sieci git.
    - Exponential backoff z jitter.
    """
    attempt = 0
    while True:
        try:
            # stdout do konsoli, żeby widać było log
            result = subprocess.run(cmd, cwd=cwd, text=True)
            if check and result.returncode != 0:
                raise subprocess.CalledProcessError(result.returncode, cmd)
            return result
        except (subprocess.CalledProcessError, OSError) as e:
            attempt += 1
            err_text = str(e)
            transient = False

            # Heurystyki tymczasowych błędów
            transient_markers = [
                "WinError 10048",           # Address already in use - port exhaustion
                "Operation timed out",
                "network is unreachable",
                "could not resolve host",
                "Connection reset by peer",
                "The remote end hung up unexpectedly",
                "RPC failed",
                "fatal: the remote end hung up unexpectedly",
                "fatal: unable to access",
            ]
            for marker in transient_markers:
                if marker.lower() in err_text.lower():
                    transient = True
                    break

            if attempt <= max_retries and transient:
                sleep_s = base_sleep * (2 ** (attempt - 1))
                # prosty jitter
                sleep_s += min(1.0, 0.2 * attempt)
                print(f"⚠️  Błąd tymczasowy przy uruchamianiu: {' '.join(cmd)}")
                print(f"    {err_text}")
                print(f"    Czekam {sleep_s:.1f}s i ponawiam... (próba {attempt}/{max_retries})")
                time.sleep(sleep_s)
                continue

            # brak retry lub limit prób wyczerpany
            print(f"❌ Polecenie nie powiodło się: {' '.join(cmd)}")
            print(f"   {err_text}")
            if check:
                raise
            return None


def ensure_prerequisites():
    if not os.path.isdir(SITE_ROOT):
        raise FileNotFoundError(f"Nie znaleziono SITE_ROOT: {SITE_ROOT}")

    index_path = os.path.join(SITE_ROOT, "index.html")
    if not os.path.isfile(index_path):
        raise FileNotFoundError(f"Brak pliku index.html w {SITE_ROOT}")

    assets_dir = os.path.join(SITE_ROOT, "assets")
    if not os.path.isdir(assets_dir):
        print(f"ℹ️  Uwaga: brak folderu assets w {SITE_ROOT} - to nie blokuje wdrożenia.")


def ensure_aux_files():
    # .nojekyll - pozwala serwować pliki z prefiksami podkreśleń itp.
    nojekyll = os.path.join(SITE_ROOT, ".nojekyll")
    if not os.path.exists(nojekyll):
        with open(nojekyll, "w", encoding="utf-8") as f:
            f.write("")
        print("✅ Utworzono .nojekyll")

    # CNAME - tylko jeśli chcesz własną domenę
    if CUSTOM_DOMAIN:
        cname = os.path.join(SITE_ROOT, "CNAME")
        with open(cname, "w", encoding="utf-8") as f:
            f.write(CUSTOM_DOMAIN.strip() + "\n")
        print(f"✅ Utworzono CNAME ({CUSTOM_DOMAIN})")


def ensure_git_config():
    # Sprawdź czy git jest dostępny
    try:
        run_cmd(["git", "--version"], check=True)
    except Exception:
        raise EnvironmentError("Nie znaleziono 'git' w PATH. Zainstaluj Git for Windows i uruchom ponownie.")

    # Przejdź do SITE_ROOT
    os.chdir(SITE_ROOT)

    # Inicjalizacja repo jeśli potrzeba
    git_dir = os.path.join(SITE_ROOT, ".git")
    if not os.path.isdir(git_dir):
        print("🔧 Inicjalizuję repozytorium git...")
        run_cmd(["git", "init"], cwd=SITE_ROOT, check=True)
        run_cmd(["git", "checkout", "-B", BRANCH], cwd=SITE_ROOT, check=True)
    else:
        # Upewnij się, że jesteśmy na właściwym branchu
        run_cmd(["git", "checkout", "-B", BRANCH], cwd=SITE_ROOT, check=True)

    # Lokalna konfiguracja usera - tylko jeśli nie ustawiona
    def get_config(key: str) -> str:
        try:
            res = subprocess.run(["git", "config", "--get", key], cwd=SITE_ROOT, text=True, capture_output=True)
            return res.stdout.strip()
        except Exception:
            return ""

    if not get_config("user.name"):
        run_cmd(["git", "config", "user.name", GITHUB_USER], cwd=SITE_ROOT, check=True)
    if not get_config("user.email"):
        # bezpieczny placeholder
        run_cmd(["git", "config", "user.email", f"{GITHUB_USER}@users.noreply.github.com"], cwd=SITE_ROOT, check=True)


def ensure_remote():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise EnvironmentError("Brak zmiennej środowiskowej GITHUB_TOKEN. Ustaw PAT z uprawnieniami repo write.")

    # HTTPS z tokenem - x-oauth-basic jako hasło
    repo_url = f"https://{token}:x-oauth-basic@github.com/{GITHUB_USER}/{GITHUB_REPO}.git"

    # Sprawdź czy jest remote origin
    res = subprocess.run(["git", "remote"], cwd=SITE_ROOT, text=True, capture_output=True)
    remotes = res.stdout.split()
    if "origin" in remotes:
        run_cmd(["git", "remote", "set-url", "origin", repo_url], cwd=SITE_ROOT, check=True)
    else:
        run_cmd(["git", "remote", "add", "origin", repo_url], cwd=SITE_ROOT, check=True)


def commit_and_push():
    # Dodaj wszystkie zmiany
    run_cmd(["git", "add", "--all"], cwd=SITE_ROOT, check=True)

    # Sprawdź czy są zmiany w staging
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=SITE_ROOT)
    if diff.returncode == 0:
        print("🟡 Brak zmian do commitowania - pomijam commit.")
    else:
        run_cmd(["git", "commit", "-m", COMMIT_MESSAGE], cwd=SITE_ROOT, check=True)

    # Push z retry
    print(f"🚀 Push na origin {BRANCH}...")
    run_cmd(["git", "push", "-u", "origin", BRANCH], cwd=SITE_ROOT, check=True)
    print("✅ Push zakończony sukcesem.")


def main():
    print("== Static site → GitHub Pages ==")
    print(f"SITE_ROOT: {SITE_ROOT}")
    ensure_prerequisites()
    ensure_aux_files()
    ensure_git_config()
    ensure_remote()
    commit_and_push()
    print("📦 Gotowe. Strona powinna być serwowana z GitHub Pages repo usera.")


if __name__ == "__main__":
    # Zapewnij prawidłowe kodowanie stdout na Windows
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
