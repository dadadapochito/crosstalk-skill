"""Install the local Codex trial without network access or third-party packages."""

import argparse
import json
import os
from pathlib import Path
import tempfile


SOURCE = Path(__file__).resolve().parent
NAME = "crosstalk-share-trial"
FILES = (
    "SKILL.md", "agents/openai.yaml", "assets/codex-agent-rule.md",
    "install.py", "INSTALL.md",
)
BEGIN = "<!-- crosstalk-share-trial:begin -->"
END = "<!-- crosstalk-share-trial:end -->"


class InstallError(Exception):
    pass


def read_optional(path):
    if path.is_symlink():
        raise InstallError(f"Inspect the symbolic link before installing: {path}")
    return path.read_bytes() if path.exists() else None


def load_preferences(home):
    path = home / "crosstalk/preferences.json"
    raw = read_optional(path)
    if raw is None:
        return path, raw, {
            "version": 1, "enabled": False, "scope": "coding_chats",
            "output_mode": "local_txt", "disabled_project_roots": [],
        }
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as error:
        raise InstallError(f"Invalid preferences; nothing reset: {path}") from error
    valid = (
        isinstance(value, dict)
        and type(value.get("version")) is int and value["version"] == 1
        and type(value.get("enabled")) is bool
        and value.get("scope") == "coding_chats"
        and value.get("output_mode") == "local_txt"
        and isinstance(value.get("disabled_project_roots"), list)
        and all(isinstance(root, str) for root in value["disabled_project_roots"])
    )
    if not valid:
        raise InstallError(f"Unsupported preferences; nothing reset: {path}")
    return path, raw, value


def encode_preferences(value, original):
    if original is not None and json.loads(original.decode("utf-8-sig")) == value:
        return original
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def instruction_change(home, rule):
    override = home / "AGENTS.override.md"
    override_raw = read_optional(override)
    active_override = override_raw and override_raw.decode("utf-8-sig").strip()
    path = override if active_override else home / "AGENTS.md"
    original = read_optional(path)
    raw = original or b""
    text = raw.decode("utf-8-sig")
    rule_text = rule.decode("utf-8-sig").strip()
    marked = f"{BEGIN}\n{rule_text}\n{END}\n"
    if BEGIN in text or END in text:
        if text.count(BEGIN) != 1 or text.count(END) != 1 or marked.strip() not in text:
            raise InstallError(f"Existing CrossTalk rule differs; inspect it first: {path}")
        return path, original, raw
    if rule_text in text:
        return path, original, raw
    if "## CrossTalk: предложения после проверенного результата" in text:
        raise InstallError(f"Existing CrossTalk rule differs; inspect it first: {path}")
    separator = b"" if not raw else (b"\n" if raw.endswith(b"\n") else b"\n\n")
    return path, original, raw + separator + marked.encode("utf-8")


def apply_changes(changes):
    for path, original, _ in changes:
        if read_optional(path) != original:
            raise InstallError(f"File changed during installation: {path}")
    for path, original, updated in changes:
        if original == updated:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".crosstalk-", delete=False) as output:
                temporary = Path(output.name)
                output.write(updated)
            if read_optional(path) != original:
                raise InstallError(f"File changed during installation: {path}")
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()


def skill_changes(home):
    changes = []
    target = home / "skills" / NAME
    if target.exists() and any(target.iterdir()) and not (target / "SKILL.md").exists():
        raise InstallError(f"An unrelated directory already exists: {target}")
    for relative in FILES:
        updated = (SOURCE / relative).read_bytes()
        path = target / relative
        original = read_optional(path)
        if original is not None and original != updated:
            raise InstallError(f"Existing skill file differs; nothing overwritten: {path}")
        changes.append((path, original, updated))
    return changes


def install(home, enable_proposals=False):
    home = Path(home).expanduser().resolve()
    path, original, preferences = load_preferences(home)
    if enable_proposals:
        preferences["enabled"] = True
    changes = skill_changes(home)
    changes.append(instruction_change(home, (SOURCE / FILES[2]).read_bytes()))
    changes.append((path, original, encode_preferences(preferences, original)))
    apply_changes(changes)
    return check(home)


def disable(home):
    home = Path(home).expanduser().resolve()
    path, original, preferences = load_preferences(home)
    if original is not None:
        preferences["enabled"] = False
        apply_changes([(path, original, encode_preferences(preferences, original))])
    return check(home)


def check(home):
    home = Path(home).expanduser().resolve()
    try:
        _, raw, preferences = load_preferences(home)
        changes = skill_changes(home)
        instruction = instruction_change(home, (SOURCE / FILES[2]).read_bytes())
        ready = raw is not None and all(old == new for _, old, new in changes + [instruction])
        return {
            "files_ready": ready,
            "proposals_enabled": preferences["enabled"],
            "output_mode": preferences["output_mode"],
            "instruction_file": str(instruction[0]),
            "runtime_verified": False,
        }
    except InstallError as error:
        return {"files_ready": False, "error": str(error), "runtime_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "check", "disable"))
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--enable-proposals", action="store_true")
    args = parser.parse_args()
    if args.enable_proposals and args.action != "install":
        parser.error("--enable-proposals is only valid with install")
    home = args.codex_home or Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    try:
        if args.action == "install":
            result = install(home, args.enable_proposals)
        elif args.action == "disable":
            result = disable(home)
        else:
            result = check(home)
    except (InstallError, OSError, UnicodeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["files_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
