#!/usr/bin/env python3
"""Construye una AppImage a partir de un paquete tar.gz.

El programa puede ejecutarse de forma independiente o desde la GitHub Action.
La configuración se obtiene de ``app.desktop`` para mantener compatibilidad con
los proyectos existentes. Las propiedades Version* son extensiones propias del
proyecto y no se copian al desktop final.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


APP_RUN_URL = (
    "https://raw.githubusercontent.com/AppImage/AppImageKit/master/resources/AppRun"
)
APPIMAGE_TOOL_URL = (
    "https://github.com/AppImage/Appimagetool/releases/download/continuous/"
    "appimagetool-x86_64.AppImage"
)
DOWNLOAD_ATTEMPTS = 5


class BuildError(RuntimeError):
    """Error controlado que puede mostrarse directamente al usuario."""


class ChecksumError(BuildError):
    """The downloaded file does not match its configured digest."""


def log(message: str) -> None:
    """Muestra una etapa del proceso con un formato uniforme."""
    print(f"==> {message}", flush=True)


def progress(label: str, current: int, total: int | None) -> None:
    """Dibuja una barra sencilla compatible con terminales y CI."""
    if not sys.stdout.isatty() or not total:
        return
    width = 30
    ratio = min(current / total, 1)
    filled = int(width * ratio)
    bar = "#" * filled + "-" * (width - filled)
    print(f"\r{label:<24} [{bar}] {ratio:>6.1%}", end="", flush=True)
    if current >= total:
        print()


def download(url: str, destination: Path, label: str, expected_sha256: str = "") -> None:
    """Descarga un archivo con reintentos y una barra de progreso.

    El archivo se escribe primero con extensión ``.part`` para no reutilizar un
    resultado incompleto si la conexión se corta.
    """
    if not url:
        raise BuildError(f"No se indicó la URL de descarga para {label}.")

    partial = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            if partial.exists():
                partial.unlink()
            request = Request(url, headers={"User-Agent": "appimage-python-builder"})
            digest = hashlib.sha256()
            with urlopen(request, timeout=60) as response, partial.open("wb") as file:
                total = int(response.headers.get("Content-Length", 0)) or None
                received = 0
                while chunk := response.read(1024 * 1024):
                    file.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    progress(label, received, total)
            actual_sha256 = digest.hexdigest()
            if expected_sha256 and actual_sha256 != expected_sha256.lower():
                raise ChecksumError(
                    f"SHA-256 mismatch for {label}: expected {expected_sha256}, "
                    f"got {actual_sha256}"
                )
            partial.replace(destination)
            return
        except ChecksumError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            if attempt == DOWNLOAD_ATTEMPTS:
                raise BuildError(
                    f"No se pudo descargar {label} después de {attempt} intentos: {error}"
                ) from error
            print(
                f"\nDescarga fallida (intento {attempt}/{DOWNLOAD_ATTEMPTS}); "
                "reintentando en 5 segundos...",
                flush=True,
            )
            time.sleep(5)


def run(
    command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> None:
    """Ejecuta un comando externo y transforma el error en un mensaje útil."""
    try:
        subprocess.run(command, cwd=cwd, check=True, env=env)
    except FileNotFoundError as error:
        raise BuildError(f"No se encontró el comando requerido: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        raise BuildError(f"El comando falló ({error.returncode}): {' '.join(command)}") from error


def read_desktop(path: Path) -> dict[str, str]:
    """Lee propiedades simples ``clave=valor`` del desktop principal."""
    if not path.is_file():
        raise BuildError(f"No existe el archivo de configuración: {path}")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def configuration(desktop: Path) -> dict[str, str]:
    """Combina la configuración del desktop con las variables del action."""
    values = read_desktop(desktop)
    action_values = {
        "VersionUrl": os.getenv("INPUT_VERSION_URL", ""),
        "VersionFile": os.getenv("INPUT_VERSION_FILE", ""),
        "VersionBash": os.getenv("INPUT_VERSION_BASH", ""),
        "VersionIcon": os.getenv("INPUT_VERSION_ICON", ""),
        "VersionDirectory": os.getenv("INPUT_VERSION_DIRECTORY", ""),
    }
    if os.getenv("GITHUB_ACTIONS", "").lower() == "true":
        values.update({key: value for key, value in action_values.items() if value})

    required = {"Name", "Exec", "Icon", "VersionUrl", "VersionFile", "VersionIcon"}
    missing = sorted(key for key in required if not values.get(key))
    if missing:
        raise BuildError("Faltan propiedades obligatorias: " + ", ".join(missing))
    return values


def find_file(root: Path, name: str) -> Path:
    """Busca un único archivo y rechaza resultados ambiguos o inexistentes."""
    matches = [path for path in root.rglob(name) if path.is_file()]
    if not matches:
        raise BuildError(f"No se encontró '{name}' dentro de {root}.")
    if len(matches) > 1:
        raise BuildError(f"Se encontraron varios archivos llamados '{name}': {matches}")
    return matches[0]


def extract_archive(archive: Path, destination: Path) -> None:
    """Extrae el paquete y evita que sus rutas escapen del directorio destino."""
    try:
        with tarfile.open(archive, mode="r:gz") as tar:
            root = destination.resolve()
            members = tar.getmembers()
            for member in members:
                target = (destination / member.name).resolve()
                if os.path.commonpath((root, target)) != str(root):
                    raise BuildError(f"El archivo contiene una ruta insegura: {member.name}")
            tar.extractall(destination)
    except (tarfile.TarError, OSError) as error:
        raise BuildError(f"No se pudo extraer {archive}: {error}") from error


def package_root(directory: Path) -> Path:
    """Aplana el único directorio raíz habitual de un tar.gz."""
    children = list(directory.iterdir())
    if len(children) == 1 and children[0].is_dir():
        root = children[0]
        for child in root.iterdir():
            shutil.move(str(child), directory / child.name)
        root.rmdir()
    return directory


def read_version(package: Path, version_file: str, command: str) -> str:
    """Obtiene la versión mediante ``version=`` o un comando compatible.

    ``VersionBash`` se conserva por compatibilidad y se ejecuta mediante shell;
    solo debe proceder de una configuración confiable del proyecto.
    """
    file_path = (package / version_file).resolve()
    if os.path.commonpath((package.resolve(), file_path)) != str(package.resolve()):
        raise BuildError(f"El archivo de versión está fuera del paquete: {version_file}")
    if not file_path.is_file():
        raise BuildError(f"No existe el archivo de versión: {file_path}")
    content = file_path.read_text(encoding="utf-8")
    if command:
        result = subprocess.run(command, input=content, text=True, shell=True, capture_output=True)
        if result.returncode:
            raise BuildError(f"No se pudo ejecutar VersionBash: {result.stderr.strip()}")
        version = result.stdout.strip()
    else:
        matches = re.findall(r"^version=(.+)$", content, flags=re.MULTILINE)
        version = matches[0].strip() if matches else ""
    if not version:
        raise BuildError(f"No se pudo obtener una versión desde {file_path}.")
    return version


def github_latest_version(app_name: str) -> str | None:
    """Obtiene la versión de la última release, si se ejecuta en GitHub."""
    repository = os.getenv("GITHUB_REPOSITORY", "")
    if not repository or "/" not in repository:
        return None
    token = os.getenv("GITHUB_TOKEN")
    headers = {"User-Agent": "appimage-python-builder", "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"https://api.github.com/repos/{repository}/releases/latest", headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            release_name = json.load(response).get("name", "")
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise BuildError(f"No se pudo consultar la última release de GitHub: {error}") from error
    prefix = f"{app_name} AppImage "
    return release_name.removeprefix(prefix) if release_name else None


def update_information(short_name: str) -> str | None:
    """Obtiene la referencia de actualización para appimagetool.

    ``auto`` usa los assets de la última release de GitHub. ``none`` desactiva
    la referencia; cualquier otro valor se pasa directamente a appimagetool.
    """
    configured = os.getenv("INPUT_UPDATE_INFORMATION", "auto").strip()
    if configured.lower() in {"none", "false", "off"}:
        return None
    if configured and configured.lower() != "auto":
        return configured
    if os.getenv("GITHUB_ACTIONS", "").lower() != "true":
        return None
    repository = os.getenv("GITHUB_REPOSITORY", "")
    if not repository or "/" not in repository:
        return None
    owner, name = repository.split("/", 1)
    prefix = short_name.replace(" ", "_")
    return f"gh-releases-zsync|{owner}|{name}|latest|{prefix}*.AppImage.zsync"


def write_action_output(name: str, value: str) -> None:
    """Publica un output moderno de GitHub Actions cuando corresponde."""
    output_file = os.getenv("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as file:
            file.write(f"{name}={value}\n")
    env_file = os.getenv("GITHUB_ENV")
    if env_file:
        with open(env_file, "a", encoding="utf-8") as file:
            file.write(f"{name.upper()}={value}\n")


def prepare_desktops(desktop: Path, app_dir: Path, short_name: str) -> None:
    """Copia los desktop y elimina las propiedades internas de construcción."""
    internal = {"VersionUrl", "VersionFile", "VersionBash", "VersionIcon", "VersionDirectory"}
    for source in sorted(desktop.parent.glob("app*.desktop")):
        output_name = source.name.replace("app", short_name, 1)
        lines = source.read_text(encoding="utf-8").splitlines()
        clean = [line for line in lines if not line.split("=", 1)[0] in internal]
        (app_dir / output_name).write_text("\n".join(clean) + "\n", encoding="utf-8")


def main() -> int:
    """Orquesta la construcción completa."""
    check = sys.argv[1] if len(sys.argv) > 1 else "force"
    version_only = sys.argv[2] if len(sys.argv) > 2 else "update"
    desktop = Path(os.getenv("APPIMAGE_DESKTOP", "app.desktop")).resolve()
    values = configuration(desktop)
    short_name = values["Name"]
    try:
        exec_name = shlex.split(values["Exec"])[0]
    except (IndexError, ValueError) as error:
        raise BuildError(f"La propiedad Exec no es válida: {values['Exec']}") from error
    app_dir = Path.cwd() / "AppDir"
    dist = Path.cwd() / "dist"

    with tempfile.TemporaryDirectory(prefix="appimage-build-") as temporary:
        work = Path(temporary)
        deploy = work / "package"
        deploy.mkdir()
        archive = work / f"{short_name}.tar.gz"
        log(f"Descargando {short_name}")
        download(
            values["VersionUrl"],
            archive,
            "Paquete",
            os.getenv("INPUT_VERSION_SHA256", "").strip(),
        )
        log(f"Extrayendo {short_name}")
        extract_archive(archive, deploy)
        package = package_root(deploy)
        version = read_version(package, values["VersionFile"], values.get("VersionBash", ""))

        if os.getenv("GITHUB_ACTIONS", "").lower() == "true" and check == "verify":
            release_version = github_latest_version(values.get("GenericName", short_name))
            update_needed = version != release_version
            write_action_output("app_update_needed", str(update_needed).lower())
            if not update_needed:
                print("No hace falta actualizar. Finalizando.")
                return 0
            if version_only == "version-only":
                print("Se solicitó únicamente comprobar la versión.")
                return 0
        elif os.getenv("GITHUB_ACTIONS", "").lower() == "true":
            write_action_output("app_update_needed", "true")

        if app_dir.exists():
            shutil.rmtree(app_dir)
        (app_dir / "usr/bin").mkdir(parents=True)
        (app_dir / "usr/share/icons/hicolor").mkdir(parents=True)
        configured_directory = values.get("VersionDirectory", "usr/bin")
        if Path(configured_directory).is_absolute():
            raise BuildError("VersionDirectory debe ser una ruta relativa a AppDir.")
        deploy_directory = app_dir / configured_directory
        deploy_directory.parent.mkdir(parents=True, exist_ok=True)
        for item in package.iterdir():
            shutil.move(str(item), deploy_directory / item.name)

        executable = find_file(app_dir, exec_name)
        binary = app_dir / "usr/bin" / exec_name
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.symlink_to(os.path.relpath(executable, binary.parent)) if not binary.exists() else None

        log("Preparando AppRun e iconos")
        app_run = app_dir / "AppRun"
        download(APP_RUN_URL, app_run, "AppRun")
        app_run.chmod(0o755)
        icon = find_file(app_dir, values["VersionIcon"])
        icon_extension = icon.suffix.lower() or ".png"
        app_icon = app_dir / f"{values['Icon']}{icon_extension}"
        shutil.copy2(icon, app_icon)
        for size in (128, 256, 512):
            target = app_dir / "usr/share/icons/hicolor" / f"{size}x{size}" / "apps"
            target.mkdir(parents=True, exist_ok=True)
            output = target / f"{short_name}{icon_extension}"
            if icon_extension == ".svg":
                shutil.copy2(icon, output)
            else:
                run(["convert", str(icon), "-resize", f"{size}x{size}", str(output)])
        prepare_desktops(desktop, app_dir, short_name)

        tool = work / "appimagetool-x86_64.AppImage"
        log("Descargando AppImageTool")
        download(APPIMAGE_TOOL_URL, tool, "AppImageTool")
        tool.chmod(0o755)
        env = os.environ.copy()
        env.update({"ARCH": "x86_64", "APPIMAGETOOL_APP_NAME": short_name.replace(" ", "_")})
        log(f"Construyendo {short_name} AppImage")
        command = [str(tool), "--comp", "zstd", str(app_dir), "-n"]
        update_url = update_information(short_name)
        if update_url:
            command.extend(["-u", update_url])
        run(command, env=env)

    dist.mkdir(exist_ok=True)
    prefix = short_name.replace(" ", "_")
    for artifact in Path.cwd().glob(f"{prefix}*.AppImage*"):
        shutil.move(str(artifact), dist / artifact.name)
    write_action_output("app_name", values.get("GenericName", short_name))
    write_action_output("app_short_name", short_name)
    write_action_output("app_version", version)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BuildError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
