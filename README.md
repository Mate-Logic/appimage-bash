# AppImage Builder

Constructor de paquetes AppImage para aplicaciones distribuidas como archivos
`.tar.gz`. El proyecto puede ejecutarse localmente o integrarse como una
GitHub Action.

[English version](#english)

## Español

### Qué hace

El constructor automatiza el proceso completo:

1. Descarga el paquete de la aplicación con reintentos.
2. Extrae y valida su contenido.
3. Obtiene la versión desde un archivo o mediante un comando configurable.
4. Comprueba si existe una release más reciente en GitHub.
5. Prepara la estructura `AppDir`.
6. Detecta el ejecutable y crea un enlace en `usr/bin` cuando hace falta.
7. Descarga `AppRun`.
8. Instala el icono en varios tamaños.
9. Copia los archivos `.desktop` y elimina la configuración interna.
10. Ejecuta `appimagetool` y deja los artefactos en `dist/`.

### Requisitos

- Linux.
- Python 3.10 o superior.
- `tar` y `appimagetool` para generar la imagen.
- `convert` de ImageMagick para iconos que no sean SVG.
- `jq` u otra herramienta que se utilice explícitamente en `VersionBash`.

El script no necesita paquetes de Python externos. Esto permite usarlo en una
GitHub Action sin un paso adicional de instalación.

### Uso como GitHub Action

```yaml
name: Release AppImage

on:
  workflow_dispatch:
  push:
    tags: ['v*']

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - name: Construir AppImage
        id: appimage
        uses: Mate-Logic/appimage-python@main
        with:
          version_url: 'https://example.org/downloads/my-app.tar.gz'
          version_file: 'my-app/version.txt'
          version_icon: 'my-app/resources/icon.png'
          version_check: 'verify'
          version_only: 'update'
```

La action recibe la configuración mediante sus inputs y genera estos outputs:

| Output | Descripción |
| --- | --- |
| `app_update_needed` | Indica si la versión descargada difiere de la última release. |
| `app_name` | Nombre genérico de la aplicación. |
| `app_short_name` | Valor de `Name` en `app.desktop`. |
| `app_version` | Versión detectada en el paquete. |

Ejemplo de uso de un output:

```yaml
- name: Mostrar versión
  run: echo "Versión: ${{ steps.appimage.outputs.app_version }}"
```

### Inputs

| Input | Obligatorio | Descripción |
| --- | --- | --- |
| `version_url` | Sí | URL del paquete `.tar.gz`. |
| `version_file` | Sí | Archivo que contiene la versión dentro del paquete. |
| `version_icon` | Sí | Nombre del icono que se utilizará. |
| `version_directory` | No | Ruta relativa dentro de `AppDir`; por defecto `usr/bin`. |
| `version_bash` | No | Comando que recibe el archivo de versión por stdin y devuelve la versión. |
| `version_check` | Sí | Usa `verify` para consultar la última release. Por defecto `verify`. |
| `version_only` | Sí | Usa `version-only` para comprobar sin construir. Por defecto `update`. |

### Uso local

El modo local lee `app.desktop` desde el directorio actual:

```bash
python3 build.py
```

Para comparar la versión descargada con la última release:

```bash
GITHUB_ACTIONS=true \
    GITHUB_REPOSITORY=Mate-Logic/appimage-python \
python3 build.py verify
```

Para comprobar solamente la versión:

```bash
GITHUB_ACTIONS=true \
    GITHUB_REPOSITORY=Mate-Logic/appimage-python \
python3 build.py verify version-only
```

Los archivos resultantes se colocan en `dist/`. Las barras de progreso se
muestran cuando la salida es una terminal interactiva; en CI se evitan los
caracteres de control innecesarios.

### Configuración de `app.desktop`

```desktop
[Desktop Entry]
Version=1.0
Type=Application
Name=MiAplicacion
GenericName=Mi Aplicación
Exec=mi-aplicacion %f
Icon=mi-aplicacion
Comment=Mi aplicación para Linux
Categories=Utility;
Terminal=false

VersionUrl=https://example.org/downloads/mi-aplicacion.tar.gz
VersionFile=resources/version.txt
VersionIcon=resources/icon.svg
VersionDirectory=opt/mi-aplicacion
```

Propiedades propias del constructor:

- `VersionUrl`: URL de descarga.
- `VersionFile`: ruta al archivo de versión dentro del paquete.
- `VersionIcon`: nombre o ruta relativa del icono dentro del paquete.
- `VersionDirectory`: ruta relativa de instalación dentro de `AppDir`.
- `VersionBash`: comando opcional para extraer la versión.

`Exec` se interpreta con reglas de shell para tomar el primer componente como
nombre del ejecutable. Los argumentos del desktop se conservan en el archivo
final, pero no se utilizan para localizar el binario.

### Estructura del proyecto

```text
.
├── action.yml
├── app.desktop
├── build.py
├── tests/
│   └── test_build.py
└── .github/workflows/
    ├── python-tests.yml
    └── shellcheck.yml
```

### Tests

Los tests usan únicamente `unittest`:

```bash
python3 -m unittest discover -s tests -v
```

La suite cubre lectura de configuración, validación de propiedades, extracción
segura, aplanado de paquetes, detección de versión y outputs de Actions.

### Seguridad y límites conocidos

- `VersionBash` se ejecuta con `shell=True` para conservar compatibilidad con
  la configuración existente. Debe contener únicamente comandos confiables.
- Las descargas se reintentan cinco veces y se escriben en archivos `.part`
  antes de reemplazar el destino final.
- Las rutas del tarball se validan para impedir escapes del directorio temporal.
- `VersionDirectory` debe ser una ruta relativa a `AppDir`.
- `AppRun` y `appimagetool` se descargan desde URLs remotas. En builds de
  producción se recomienda fijar versiones y validar checksums.
- Actualmente el artefacto está orientado a `x86_64`.

### Licencia

Este proyecto se distribuye bajo la [Licencia MIT](LICENSE).

### Origen y mantenimiento

Este repositorio comenzó como un fork de
[`valicm/appimage-bash`](https://github.com/valicm/appimage-bash). La
migración a Python, las mejoras de validación, los tests y el mantenimiento
actual son responsabilidad de Mate-Logic. Se conserva la licencia MIT y la
atribución del proyecto original.

<a id="english"></a>

## English

### Overview

AppImage builder for applications distributed as `.tar.gz` archives. It can be
run locally or used as a GitHub Action.

The Python builder downloads and validates the archive, detects its version,
prepares `AppDir`, installs `AppRun`, creates icon sizes, copies desktop files,
and runs `appimagetool`. Build artifacts are written to `dist/`.

### Requirements

- Linux.
- Python 3.10 or newer.
- `tar` and `appimagetool` support.
- ImageMagick `convert` for non-SVG icons.
- `jq` or another command explicitly referenced by `VersionBash`.

No third-party Python packages are required.

### GitHub Action

```yaml
- uses: actions/checkout@v4
- name: Build AppImage
  id: appimage
  uses: Mate-Logic/appimage-python@main
  with:
    version_url: 'https://example.org/downloads/my-app.tar.gz'
    version_file: 'my-app/version.txt'
    version_icon: 'my-app/resources/icon.png'
```

Available inputs are `version_url`, `version_file`, `version_icon`,
`version_directory`, `version_bash`, `version_check`, and `version_only`.
The action exposes `app_update_needed`, `app_name`, `app_short_name`, and
`app_version` outputs.

### Local execution

Place an `app.desktop` file in the working directory and run:

```bash
python3 build.py
python3 build.py verify
python3 build.py verify version-only
```

The `Version*` desktop properties configure the download URL, version file,
version command, icon, and deployment directory. See the Spanish section above
for a complete configuration example.

### Development

Run the test suite with:

```bash
python3 -m unittest discover -s tests -v
```

The implementation uses the Python standard library, temporary build
directories, retryable downloads, safe archive path checks, and modern
`GITHUB_OUTPUT` support.

### Security notes

Only trusted projects should provide `VersionBash`, because it is intentionally
executed through a shell for backwards compatibility. Production pipelines
should pin remote tool versions and verify checksums. The current artifact
target is `x86_64`.

### License

This project is released under the [MIT License](LICENSE).

### Origin and maintenance

This repository started as a fork of
[`valicm/appimage-bash`](https://github.com/valicm/appimage-bash). The Python
migration, validation improvements, tests, and current maintenance are
provided by Mate-Logic. The original project's MIT license and attribution
are preserved.
