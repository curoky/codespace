from __future__ import annotations

import json
import os
import pwd
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

BIN = Path("/opt/codespace/bin")
HOME = Path("/home/x")
S6_PROFILE = Path("/opt/bm/profile/s6")
S6_BIN = S6_PROFILE / "bin"
EXTENSION_TEMPLATE = Path("/opt/codespace/share/editor-extensions")
SERVERS = (".vscode-server", ".trae-server", ".trae-cn-server")
EDITOR_HOMES = (*SERVERS, ".trae", ".trae-cn")


def run(
    *args: str | Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(arg) for arg in args],
        check=check,
        capture_output=True,
        text=True,
        env=env,
    )


class TestImageContract(unittest.TestCase):
    def test_agent_runtime_imports_and_builds_app(self) -> None:
        agent_python = Path("/opt/codespace/agent/.venv/bin/python")
        env = {**os.environ, "PYTHONPATH": "/opt/codespace/agent"}
        code = (
            "import agent; "
            "workspace = agent.WorkspaceAgent('empty', '/workspace', '/workspace'); "
            "app = agent.create_app(workspace); "
            "print('\\n'.join(sorted(route.path for route in app.routes)))"
        )

        result = run(agent_python, "-c", code, env=env)

        self.assertEqual(result.stdout.splitlines(), ["/git-state", "/provider-ready", "/status"])

    def test_critical_commands_start(self) -> None:
        self.assertEqual(shutil.which("execlineb"), str(S6_BIN / "execlineb"))
        commands = {
            # python3 resolves through the uv-managed prefix, not PATH.
            "/opt/uv/bin/python3": ("--version",),
            "git": ("--version",),
            "ssh": ("-V",),
            "sudo": ("-V",),
            "gocryptfs": ("-version",),
            "nixcache": ("serve", "--host", "127.0.0.1", "--port", "8009", "--help"),
        }
        for command, arguments in commands.items():
            with self.subTest(command=command):
                executable = command if Path(command).is_absolute() else shutil.which(command)
                self.assertIsNotNone(executable)
                result = run(executable, *arguments)
                self.assertTrue(result.stdout or result.stderr)

    def test_runtime_files_have_required_permissions(self) -> None:
        helpers = sorted(BIN.iterdir())
        self.assertTrue(helpers)
        for helper in helpers:
            with self.subTest(helper=helper):
                self.assertTrue(helper.is_file())
                self.assertTrue(os.access(helper, os.X_OK))

        for private_key in sorted(Path("/etc/ssh").glob("ssh_host_*_key")):
            with self.subTest(private_key=private_key):
                metadata = private_key.stat()
                self.assertEqual((metadata.st_uid, metadata.st_gid), (0, 0))
                self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o600)

        self.assertGreaterEqual(len(list(Path("/etc/ssh").glob("ssh_host_*_key"))), 2)
        protected_files = (
            Path("/etc/sudoers"),
            Path("/etc/sudoers.d/more_secure_path"),
            Path("/etc/sudoers.d/nopasswd_user"),
        )
        for path in protected_files:
            with self.subTest(path=path):
                metadata = path.stat()
                self.assertEqual((metadata.st_uid, metadata.st_gid), (0, 0))
                self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o440)

        ssh_directory = HOME / ".ssh"
        authorized_keys = ssh_directory / "authorized_keys"
        self.assertEqual((ssh_directory.stat().st_uid, ssh_directory.stat().st_gid), (5230, 5230))
        self.assertEqual(stat.S_IMODE(ssh_directory.stat().st_mode), 0o700)
        self.assertEqual(
            (authorized_keys.stat().st_uid, authorized_keys.stat().st_gid),
            (5230, 5230),
        )
        self.assertFalse((ssh_directory / "workspace_login_key_ed25519").exists())
        self.assertFalse((ssh_directory / "workspace_login_key_ed25519.pub").exists())
        agent_state = Path("/var/lib/codespace")
        self.assertTrue(agent_state.is_dir())
        self.assertEqual((agent_state.stat().st_uid, agent_state.stat().st_gid), (0, 0))
        self.assertEqual(stat.S_IMODE(agent_state.stat().st_mode), 0o700)

    def test_s6_database_contains_workspace_service_graph(self) -> None:
        database = Path("/etc/s6/db")
        s6_rc_db = S6_BIN / "s6-rc-db"
        expected_services = {
            "atuin-daemon",
            "atuin-login",
            "atuin-server",
            "copyparty-webdav",
            "gh-login",
            "git-config",
            "home-init",
            "hosts-blackhole",
            "miniserve-http",
            "nixcache",
            "ollama",
            "rclone-http",
            "rclone-webdav",
            "secret-mount",
            "sshd",
            "supercronic",
            "workspace-agent",
            "workspace-init",
        }

        services = set(run(s6_rc_db, "-c", database, "list", "all").stdout.splitlines())
        default_services = set(
            run(s6_rc_db, "-c", database, "contents", "default").stdout.splitlines()
        )
        sshd_dependencies = set(
            run(s6_rc_db, "-c", database, "dependencies", "sshd").stdout.splitlines()
        )
        agent_dependencies = set(
            run(
                s6_rc_db,
                "-c",
                database,
                "dependencies",
                "workspace-agent",
            ).stdout.splitlines()
        )

        self.assertLessEqual(expected_services, services)
        self.assertEqual(default_services, expected_services)
        self.assertEqual(sshd_dependencies, {"home-init", "workspace-init"})
        self.assertEqual(agent_dependencies, {"sshd"})
        # s6-rc-compile injects s6rc-oneshot-runner as an implicit dependency of
        # every oneshot service, so home-init is never dependency-free.
        self.assertEqual(
            set(run(s6_rc_db, "-c", database, "dependencies", "home-init").stdout.splitlines()),
            {"s6rc-oneshot-runner"},
        )

    def test_ssh_listener_and_readiness_contract(self) -> None:
        sshd = "/opt/bm/store/openssh_gssapi/bin/sshd"
        run("sudo", sshd, "-t")
        # sshd -T keeps the original casing for some keywords (e.g.
        # PubkeyAuthentication) while lowercasing others; normalize before matching.
        config = [line.lower() for line in run("sudo", sshd, "-T").stdout.splitlines()]
        for setting in (
            "port 22",
            "listenaddress 0.0.0.0:22",
            "pubkeyauthentication yes",
            "passwordauthentication no",
            "authorizedkeysfile .ssh/authorized_keys",
            "hostkey /etc/ssh/ssh_host_ed25519_key",
        ):
            self.assertIn(setting, config)
        service = Path("/etc/s6/s6-rc.d/sshd")
        self.assertEqual((service / "notification-fd").read_text().strip(), "3")
        self.assertIsNotNone(self.locate_s6_tool("s6-notifyoncheck"))
        self.assertIsNotNone(self.locate_s6_tool("s6-tcpclient"))

    @staticmethod
    def locate_s6_tool(name: str) -> Path | None:
        # s6 splits user commands into bin and internal helpers into libexec, so
        # readiness tools may live in either directory of the merged profile.
        for directory in (S6_PROFILE / "bin", S6_PROFILE / "libexec"):
            candidate = directory / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
        return None

    def test_user_and_home_configuration(self) -> None:
        user = pwd.getpwnam("x")
        self.assertEqual((user.pw_uid, user.pw_gid, user.pw_dir), (5230, 5230, "/home/x"))
        self.assertEqual(os.getuid(), 5230)

        links = {
            ".trae-cn/sandbox.json": "../.trae/sandbox.json",
            ".trae-cn/traecli.toml": "../.trae/traecli.toml",
            ".trae-server/data/Machine/settings.json": (
                "../../../.vscode-server/data/Machine/settings.json"
            ),
            ".trae-cn-server/data/Machine/settings.json": (
                "../../../.vscode-server/data/Machine/settings.json"
            ),
        }
        for relative_path, target in links.items():
            with self.subTest(path=relative_path):
                self.assertEqual(str((HOME / relative_path).readlink()), target)

        for editor_home in EDITOR_HOMES:
            for leaf in ("bin", "extensions"):
                with self.subTest(editor_home=editor_home, leaf=leaf):
                    self.assertFalse((HOME / editor_home / leaf).is_symlink())
        self.assertFalse(os.path.lexists("/cache"))

        settings = (HOME / ".vscode-server/data/Machine/settings.json").read_text()
        self.assertIn(
            '"python.defaultInterpreterPath": "/opt/uv/bin/python3",',
            settings,
        )
        self.assertNotIn('"python.defaultInterpreterPath": "/opt/conda/', settings)

        condarc = (HOME / ".config/conda/condarc").read_text()
        zshrc = (HOME / ".zshrc").read_text()
        self.assertIn("auto_activate: false", condarc)
        self.assertNotIn("conda activate", zshrc)
        self.assertIn('source "/opt/conda/etc/profile.d/conda.sh"', zshrc)
        self.assertIn(
            'source "/opt/bm/store/starship/share/starship/init.zsh"',
            zshrc,
        )
        self.assertIn('source "/opt/bm/store/atuin/share/atuin/init.zsh"', zshrc)

    def test_editor_extension_template_is_complete(self) -> None:
        payload = EXTENSION_TEMPLATE / "extensions"
        self.assertTrue(payload.is_dir())
        self.assertFalse((payload / "extensions.json").exists())

        manifests = []
        for server in SERVERS:
            manifest = json.loads((EXTENSION_TEMPLATE / f"{server}.json").read_text())
            self.assertTrue(manifest)
            manifests.append(manifest)
            for entry in manifest:
                relative = entry["relativeLocation"]
                self.assertEqual(
                    entry["location"]["path"],
                    f"/home/x/{server}/extensions/{relative}",
                )
                self.assertTrue((payload / relative).is_dir())

        identifiers = [
            {(entry["identifier"]["id"], entry["version"]) for entry in manifest}
            for manifest in manifests
        ]
        self.assertEqual(identifiers[1:], identifiers[:1] * (len(identifiers) - 1))


class TestCheckout(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(prefix="checkout.")
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def init_repository(self, target: Path) -> None:
        run("git", "init", "-q", target)
        run("git", "-C", target, "config", "user.name", "Codespace Test")
        run("git", "-C", target, "config", "user.email", "codespace@example.com")

    def create_origin(self, name: str = "origin.git") -> Path:
        seed = self.root / f"{name}.seed"
        origin = self.root / name
        self.init_repository(seed)
        (seed / "README.md").write_text("initial\n")
        run("git", "-C", seed, "add", "README.md")
        run("git", "-C", seed, "commit", "-qm", "initial")
        for index in range(2):
            (seed / "README.md").write_text(f"revision {index + 2}\n")
            run("git", "-C", seed, "commit", "-qam", f"revision {index + 2}")
        run("git", "clone", "-q", "--bare", seed, origin)
        return origin

    def test_checkout_clone_reuse_empty_and_invalid_targets(self) -> None:
        helper = BIN / "checkout"
        origin = self.create_origin()
        checkout = self.root / "workspace/repository"

        result = run(helper, f"file://{origin}", checkout)
        self.assertEqual(result.stdout, "")
        self.assertTrue((checkout / ".git").is_dir())
        self.assertEqual(run("git", "-C", checkout, "rev-list", "--count", "HEAD").stdout, "3\n")
        self.assertEqual(
            run("git", "-C", checkout, "rev-parse", "--is-shallow-repository").stdout,
            "false\n",
        )

        shallow_checkout = self.root / "workspace/shallow"
        run(helper, f"file://{origin}", shallow_checkout, "--depth=1", "--single-branch")
        self.assertEqual(
            run("git", "-C", shallow_checkout, "rev-list", "--count", "HEAD").stdout,
            "1\n",
        )
        self.assertEqual(
            run("git", "-C", shallow_checkout, "rev-parse", "--is-shallow-repository").stdout,
            "true\n",
        )

        local_file = checkout / "local.txt"
        local_file.write_text("local\n")
        run(helper, f"file://{origin}", checkout)
        self.assertTrue(local_file.is_file())

        empty_origin = self.root / "empty.git"
        run("git", "init", "-q", "--bare", empty_origin)
        empty_checkout = self.root / "workspace/empty"
        run(helper, f"file://{empty_origin}", empty_checkout)
        self.assertTrue((empty_checkout / ".git/codespace-empty-repository").is_file())

        occupied = self.root / "workspace/occupied"
        occupied.mkdir()
        occupied_file = occupied / "keep.txt"
        occupied_file.write_text("keep\n")
        result = run(helper, f"file://{origin}", occupied, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("exists but is not a checkout", result.stderr)
        self.assertTrue(occupied_file.is_file())

        incomplete = self.root / "workspace/incomplete"
        self.init_repository(incomplete)
        incomplete_file = incomplete / "keep.txt"
        incomplete_file.write_text("uncommitted work\n")
        result = run(helper, f"file://{origin}", incomplete, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a reusable checkout", result.stderr)
        self.assertEqual(incomplete_file.read_text(), "uncommitted work\n")
        self.assertFalse((incomplete / "README.md").exists())

        result = run(helper, "only-one", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage: checkout", result.stderr)


class TestRuntimeHelpers(unittest.TestCase):
    def test_home_init_is_idempotent_and_preserves_editor_state(self) -> None:
        for server in SERVERS[1:]:
            target = HOME / server / "extensions"
            run("sudo", "install", "-d", "-o", "5230", "-g", "5230", "-m", "0700", target)
            (target / "extensions.json").write_text("[]\n")

        # Bind sources prepared by the Host need not arrive owned by x.
        for editor_home in EDITOR_HOMES:
            for leaf in ("bin", "extensions"):
                run(
                    "sudo",
                    "install",
                    "-d",
                    "-o",
                    "0",
                    "-g",
                    "0",
                    "-m",
                    "0755",
                    HOME / editor_home / leaf,
                )

        run(BIN / "init-home")

        private_key = HOME / ".ssh/git_deploy_key_ed25519"
        public_key = HOME / ".ssh/git_deploy_key_ed25519.pub"
        self.assertTrue(private_key.is_file())
        self.assertTrue(public_key.is_file())
        self.assertEqual(stat.S_IMODE(private_key.stat().st_mode), 0o600)
        first_public_key = public_key.read_text()

        vscode_extensions = HOME / ".vscode-server/extensions"
        manifest = vscode_extensions / "extensions.json"
        self.assertTrue(manifest.is_file())
        installed = json.loads(manifest.read_text())
        self.assertTrue(installed)
        removed = vscode_extensions / installed[0]["relativeLocation"]
        shutil.rmtree(removed)
        manifest.write_text("[]\n")

        run(BIN / "init-home")

        self.assertEqual(public_key.read_text(), first_public_key)
        self.assertEqual(json.loads(manifest.read_text()), [])
        self.assertFalse(removed.exists())
        for editor_home in EDITOR_HOMES:
            for leaf in ("bin", "extensions"):
                path = HOME / editor_home / leaf
                self.assertTrue(path.is_dir())
                self.assertFalse(path.is_symlink())
                self.assertEqual((path.stat().st_uid, path.stat().st_gid), (5230, 5230))
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)

    def test_workspace_init_validates_mode_and_prepares_plaintext_paths(self) -> None:
        helper = BIN / "init-workspace"
        # A Host login UID can differ from x; initialization must retain it.
        control = Path("/run/codespace-control")
        run("sudo", "install", "-d", "-o", "200", "-g", "65534", "-m", "0755", control)

        env = os.environ.copy()
        env["CODESPACE_ENCRYPTED_PATH"] = "/workspace.enc"
        env.pop("CODESPACE_ENCRYPTED", None)
        result = run(helper, env=env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CODESPACE_ENCRYPTED must be true or false", result.stderr)

        env["CODESPACE_ENCRYPTED"] = "invalid"
        result = run(helper, env=env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr.strip(), "CODESPACE_ENCRYPTED must be true or false")

        env["CODESPACE_ENCRYPTED"] = "false"
        env.pop("CODESPACE_ENCRYPTED_PATH")
        result = run(helper, env=env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CODESPACE_ENCRYPTED_PATH must be set", result.stderr)

        env["CODESPACE_ENCRYPTED_PATH"] = "/workspace.enc"
        env["CODESPACE_ENCRYPTED"] = "true"
        result = run(helper, env=env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            result.stderr.strip(),
            "Encrypted Workspace requires a readable key secret",
        )

        env["CODESPACE_ENCRYPTED"] = "false"
        result = run(helper, env=env)
        self.assertEqual(
            result.stdout.strip(),
            "Workspace encryption disabled, using plaintext /workspace",
        )
        for path in (Path("/workspace"), Path("/workspace.enc"), Path("/upload")):
            with self.subTest(path=path):
                self.assertTrue(path.is_dir())
                self.assertFalse(path.is_symlink())
                self.assertEqual((path.stat().st_uid, path.stat().st_gid), (5230, 5230))
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        self.assertEqual((control.stat().st_uid, control.stat().st_gid), (200, 65534))
        self.assertEqual(stat.S_IMODE(control.stat().st_mode), 0o700)
        marker = Path("/workspace/keep")
        marker.write_text("persistent\n")
        run(helper, env=env)
        self.assertEqual(marker.read_text(), "persistent\n")
        self.assertEqual((control.stat().st_uid, control.stat().st_gid), (200, 65534))


if __name__ == "__main__":
    unittest.main(verbosity=2)
