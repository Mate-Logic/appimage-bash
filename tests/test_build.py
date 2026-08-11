import os
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import build


class BuildTests(unittest.TestCase):
    def test_read_desktop_ignora_comentarios_y_conserva_valores(self):
        with TemporaryDirectory() as temporary:
            desktop = Path(temporary) / "app.desktop"
            desktop.write_text(
                "# comentario\nName=Mi App\nVersionUrl=https://example.test/a=b\n",
                encoding="utf-8",
            )

            values = build.read_desktop(desktop)

        self.assertEqual(values["Name"], "Mi App")
        self.assertEqual(values["VersionUrl"], "https://example.test/a=b")
        self.assertNotIn("# comentario", values)

    def test_configuration_falla_si_falta_una_propiedad(self):
        with TemporaryDirectory() as temporary:
            desktop = Path(temporary) / "app.desktop"
            desktop.write_text("Name=App\nExec=app\n", encoding="utf-8")

            with self.assertRaisesRegex(build.BuildError, "Faltan propiedades"):
                build.configuration(desktop)

    def test_extract_archive_rechaza_rutas_fuera_del_destino(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "unsafe.tar.gz"
            destination = root / "destination"
            destination.mkdir()
            with tarfile.open(archive, "w:gz") as tar:
                info = tarfile.TarInfo("../../outside.txt")
                info.size = 5
                import io

                tar.addfile(info, io.BytesIO(b"owned"))

            with self.assertRaisesRegex(build.BuildError, "ruta insegura"):
                build.extract_archive(archive, destination)

    def test_package_root_aplana_un_directorio_raiz(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            nested = directory / "app-1.0"
            nested.mkdir()
            (nested / "version.txt").write_text("ok", encoding="utf-8")

            result = build.package_root(directory)

            self.assertEqual(result, directory)
            self.assertTrue((directory / "version.txt").is_file())
            self.assertFalse(nested.exists())

    def test_read_version_lee_version_estandar(self):
        with TemporaryDirectory() as temporary:
            package = Path(temporary)
            version_file = package / "version.env"
            version_file.write_text("version=1.2.3\n", encoding="utf-8")

            self.assertEqual(build.read_version(package, "version.env", ""), "1.2.3")

    def test_read_version_puede_usar_comando_compatible(self):
        with TemporaryDirectory() as temporary:
            package = Path(temporary)
            (package / "version.txt").write_text("version=1.2.3\n", encoding="utf-8")

            self.assertEqual(
                build.read_version(package, "version.txt", "tr a-z A-Z"),
                "VERSION=1.2.3",
            )

    def test_write_action_output_escribe_output_y_entorno(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            environment = Path(temporary) / "environment"
            with patch.dict(
                os.environ,
                {"GITHUB_OUTPUT": str(output), "GITHUB_ENV": str(environment)},
                clear=False,
            ):
                build.write_action_output("app_update_needed", "false")

            self.assertEqual(output.read_text(encoding="utf-8"), "app_update_needed=false\n")
            self.assertEqual(environment.read_text(encoding="utf-8"), "APP_UPDATE_NEEDED=false\n")


if __name__ == "__main__":
    unittest.main()
