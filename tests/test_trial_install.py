import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "skills" / "crosstalk-share-trial"
SPEC = importlib.util.spec_from_file_location("trial_install", SOURCE / "install.py")
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class TrialInstallTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="crosstalk-install-test-")
        self.home = Path(self.temporary.name).resolve() / "codex"

    def tearDown(self):
        temporary_root = Path(self.temporary.name).resolve()
        self.assertEqual(temporary_root.parent, Path(tempfile.gettempdir()).resolve())
        self.temporary.cleanup()

    def write(self, relative, content):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def snapshot(self):
        return {
            str(path.relative_to(self.home)): path.read_bytes()
            for path in self.home.rglob("*") if path.is_file()
        }

    def test_fresh_install_needs_explicit_opt_in(self):
        installer.install(self.home)
        self.assertTrue(installer.check(self.home)["files_ready"])
        self.assertFalse(installer.check(self.home)["proposals_enabled"])
        installer.install(self.home, enable_proposals=True)
        self.assertTrue(installer.check(self.home)["proposals_enabled"])

    def test_repeat_install_is_identical_and_keeps_existing_instructions(self):
        original = "# Мои правила\r\nНе трогай рабочий сервер.\r\n".encode("utf-8")
        instructions = self.write("AGENTS.md", original)
        installer.install(self.home, enable_proposals=True)
        self.assertTrue(instructions.read_bytes().startswith(original))
        before = self.snapshot()
        installer.install(self.home, enable_proposals=True)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(instructions.read_text(encoding="utf-8").count(installer.BEGIN), 1)

    def test_existing_choices_and_extra_preferences_survive(self):
        preferences = {
            "version": 1, "enabled": False, "scope": "coding_chats",
            "output_mode": "local_txt", "disabled_project_roots": ["D:/Private"],
            "custom_note": "keep",
        }
        original = json.dumps(preferences).encode()
        path = self.write("crosstalk/preferences.json", original)
        installer.install(self.home)
        self.assertEqual(path.read_bytes(), original)
        installer.install(self.home, enable_proposals=True)
        preferences["enabled"] = True
        self.assertEqual(json.loads(path.read_bytes()), preferences)

    def test_effective_override_is_updated_and_base_is_preserved(self):
        base = self.write("AGENTS.md", b"Base instructions.\n")
        override = self.write("AGENTS.override.md", b"Active instructions.\n")
        installer.install(self.home, enable_proposals=True)
        self.assertEqual(base.read_bytes(), b"Base instructions.\n")
        self.assertTrue(override.read_bytes().startswith(b"Active instructions.\n"))
        self.assertEqual(installer.check(self.home)["instruction_file"], str(override))

    def test_legacy_manual_install_does_not_duplicate_rule(self):
        original = (SOURCE / "assets/codex-agent-rule.md").read_bytes()
        instructions = self.write("AGENTS.md", original)
        installer.install(self.home, enable_proposals=True)
        self.assertEqual(instructions.read_bytes(), original)

    def test_invalid_preferences_fail_before_installation_writes(self):
        self.write("crosstalk/preferences.json", b'{"version": 999}')
        before = self.snapshot()
        with self.assertRaises(installer.InstallError):
            installer.install(self.home, enable_proposals=True)
        self.assertEqual(self.snapshot(), before)

    def test_modified_skill_is_not_overwritten_or_reenabled(self):
        installer.install(self.home)
        self.write("skills/crosstalk-share-trial/SKILL.md", b"My edits.\n")
        before = self.snapshot()
        with self.assertRaises(installer.InstallError):
            installer.install(self.home, enable_proposals=True)
        self.assertEqual(self.snapshot(), before)

    def test_disable_preserves_files_and_reinstall_keeps_disabled_choice(self):
        installer.install(self.home, enable_proposals=True)
        before = self.snapshot()
        installer.disable(self.home)
        after = self.snapshot()
        changed = [name for name in before if before[name] != after[name]]
        self.assertEqual(changed, [str(Path("crosstalk/preferences.json"))])
        installer.install(self.home)
        self.assertFalse(installer.check(self.home)["proposals_enabled"])
        self.assertTrue(installer.check(self.home)["files_ready"])

    def test_installed_package_can_check_and_disable_itself(self):
        installer.install(self.home, enable_proposals=True)
        installed = self.home / "skills" / installer.NAME
        for action in ("check", "disable"):
            result = subprocess.run(
                [sys.executable, str(installed / "install.py"), action,
                 "--codex-home", str(self.home)],
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            status = json.loads(result.stdout)
            self.assertTrue(status["files_ready"])
            self.assertEqual(status["proposals_enabled"], action == "check")
        self.assertTrue((installed / "INSTALL.md").is_file())

    def test_downloaded_skill_can_complete_setup_in_place(self):
        installed = self.home / "skills" / installer.NAME
        shutil.copytree(SOURCE, installed)
        result = subprocess.run(
            [sys.executable, str(installed / "install.py"), "install",
             "--enable-proposals", "--codex-home", str(self.home)],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        status = json.loads(result.stdout)
        self.assertTrue(status["files_ready"])
        self.assertTrue(status["proposals_enabled"])
        self.assertTrue((self.home / "AGENTS.md").is_file())


if __name__ == "__main__":
    unittest.main()
