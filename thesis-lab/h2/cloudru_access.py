"""Store Cloud.ru H2 credentials locally and check IAM authentication only.

Run interactively in WSL. No cloud resources are created. Credentials remain
outside the repository; bearer tokens are neither printed nor persisted.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import stat
import sys
import urllib.error
import urllib.request
import uuid
import warnings

PROFILE = Path.home() / ".config/firefly-thesis/cloudru/credentials.json"
TOKEN_URL = "https://iam.api.cloud.ru/api/v2/auth/token"


class AccessError(Exception):
    """Only locally authored, nonsecret diagnostics may enter this exception."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward credentials or tokens to a redirect destination.
        return None


def validate(profile):
    if not isinstance(profile, dict):
        raise AccessError("Некорректный формат локального профиля.")
    try:
        project_id = str(uuid.UUID(profile["project_id"]))
    except (KeyError, ValueError, TypeError, AttributeError):
        raise AccessError("Project ID должен быть UUID проекта Cloud.ru.") from None
    for field in ("key_id", "key_secret"):
        value = profile.get(field)
        if not isinstance(value, str) or not value or value != value.strip():
            raise AccessError("Key ID и Key Secret должны быть непустыми, без пробелов по краям.")
    return {"project_id": project_id, "key_id": profile["key_id"],
            "key_secret": profile["key_secret"]}


def save_profile(profile, path=PROFILE):
    profile = validate(profile)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise AccessError("Каталог профиля не должен быть символической ссылкой.")
    path.parent.chmod(0o700)
    # Exclusive creation prevents accidental credential replacement and follows
    # neither existing files nor symlinks. Mode is restrictive from creation.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(profile, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def load_profile(path=PROFILE):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise AccessError("Профиль должен принадлежать текущему пользователю и иметь права 600.")
        try:
            profile = json.load(stream)
        except (ValueError, UnicodeError):
            raise AccessError("Локальный профиль повреждён; данные не выводятся.") from None
    return validate(profile)


def authenticate(profile):
    profile = validate(profile)
    request = urllib.request.Request(
        TOKEN_URL,
        data=json.dumps({"keyId": profile["key_id"], "secret": profile["key_secret"]}).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        raise AccessError(f"Cloud.ru IAM вернул HTTP {code}. Проверьте ключ и статус аккаунта.") from None
    except (urllib.error.URLError, OSError):
        raise AccessError("Не удалось соединиться с Cloud.ru IAM. Повторите проверку позже.") from None
    except (ValueError, UnicodeError):
        raise AccessError("Cloud.ru IAM вернул некорректный JSON; тело ответа не выводится.") from None
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise AccessError("В ответе Cloud.ru IAM отсутствует access_token; тело ответа не выводится.")
    return token


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Проверить уже сохранённый профиль")
    args = parser.parse_args(argv)
    try:
        if args.check:
            profile = load_profile()
        else:
            if PROFILE.exists() or PROFILE.is_symlink():
                raise AccessError("Профиль уже существует. Для повторной проверки используйте --check.")
            if not sys.stdin.isatty():
                raise AccessError("Запустите команду в интерактивном терминале WSL.")
            print("Настройка доступа к Cloud.ru для H2. Платные ресурсы не создаются.")
            project_id = input("Project ID (UUID): ").strip()
            with warnings.catch_warnings():
                # Refuse getpass's echoing fallback on terminals without echo control.
                warnings.simplefilter("error", getpass.GetPassWarning)
                key_id = getpass.getpass("Key ID (ввод скрыт): ")
                key_secret = getpass.getpass("Key Secret (ввод скрыт): ")
            profile = validate({"project_id": project_id, "key_id": key_id, "key_secret": key_secret})
            save_profile(profile)
            print(f"Профиль сохранён: {PROFILE} (права 600, каталог 700).")
            print("При сетевой ошибке можно повторить только проверку с --check.")
        authenticate(profile)
    except AccessError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except getpass.GetPassWarning:
        print("Терминал не поддерживает скрытый ввод. Используйте обычный терминал WSL.", file=sys.stderr)
        return 1
    except (OSError, EOFError):
        print("Не удалось прочитать ввод или локальный профиль. Данные не выводятся.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nНастройка прервана.", file=sys.stderr)
        return 130
    print("Авторизация Cloud.ru IAM успешна. Ключ и токен не выводятся.")
    print("Права на проект, квоты и Billing ещё предстоит проверить. Ресурсы не создавались.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
