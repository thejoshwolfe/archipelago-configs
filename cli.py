#!/usr/bin/env python3

__doc__ = """\
Invokes the Archipelago tools with CLI ergonomics more suitable to stateless automation.
"""

import os, sys, subprocess
import shutil, shlex, tempfile
import re, json

def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", metavar="/path/to/Archipelago", required=True, help=
        "Path to a clone of https://github.com/ArchipelagoMW/Archipelago .")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    sub_parser = subparsers.add_parser("update", help=
        "effectively runs 'git pull' in the --repo, then runs the 'init' command.")
    sub_parser = subparsers.add_parser("init", help=
        "initializes a venv at {repo}/.venv (if not present) using this python, "
        "then runs ModuleUpdate.py, which runs pip install. "
        "All other invocations of Archipelago scripts from this wrapper set SKIP_REQUIREMENTS_UPDATE=1, "
        "so running 'init' is *required* after a fresh install.")

    sub_parser = subparsers.add_parser("generate", help=
        "Calls Generate.py with different CLI ergonomics.")
    group = sub_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--output-zip", help=
        "Moves the output .zip to the given path. Overwritten if exists.")
    group.add_argument("--output-dir", help=
        "Extracts the output .zip file into the given directory. "
        "Created if it doesn't exist; error if exists and not empty.")
    sub_parser.add_argument("--seed", metavar="int", type=int, default=-1, help=
        "Forwarded to Generate.py '--seed'.")
    sub_parser.add_argument("player_yaml", nargs="+", help=
        "Path(s) to player .yaml files. "
        "These get copied into a tmp dir and given to Generate.py '--player_files_path'. ")

    sub_parser = subparsers.add_parser("factorio", help=
        "How I, a NixOS user, invoke the AP client for Factorio, which runs the Factorio headless server in a docker container. "
        "Requires docker and a downloaded standalone factorio installation. "
        "First, run 'generate' and start the archipelago server, then run this command. "
        "Use the /connect command to connect to the archipelago game, which automatically launches the factorio server locally. "
        "Once the factorio server is running, launch the factorio gui normally (via steam or whatever), and connect to localhost.")
    sub_parser.add_argument("--factorio", metavar="/path/to/standalone/factorio", required=True, help=
        "Download it from https://factorio.com/download . "
        "The dir should contain bin/, data/, etc.")
    sub_parser.add_argument("--mod", metavar="/path/to/AP-*.zip", required=True, help=
        "The mod .zip produced by the 'generate' command. It's got your name in the file name.")
    sub_parser.add_argument("--server-dir", required=True, help=
        "The cwd for the factorio server. "
        "The save file called Archipelago.zip goes there, and this script throws stuff in there as well.")

    args = parser.parse_args()

    if args.cmd == "update":
        do_update(args.repo)
    elif args.cmd == "init":
        do_init(args.repo)
    elif args.cmd == "generate":
        do_generate(args.repo, args.output_zip, args.output_dir, args.seed, args.player_yaml)
    elif args.cmd == "factorio":
        do_factorio(args.repo, args.mod, args.factorio, args.server_dir)
    else: assert False

def do_update(repo):
    def git(*args, stdout=None):
        cmd = ["git"]
        cmd.extend(args)
        process = subprocess.run(cmd, stdout=stdout, check=True, cwd=repo)
        return process.stdout

    if len(git("status", "--porcelain", stdout=subprocess.PIPE)) > 0:
        sys.exit("ERROR: git status not clean: " + repo)

    git("fetch", "--prune")
    git("status")
    git("merge", "--ff", "@{upstream}")

    do_init(repo)

def do_init(repo):
    venv_dir = os.path.join(repo, ".venv")
    python_exe = os.path.join(venv_dir, "bin", "python")
    if not os.path.isfile(python_exe):
        import venv
        builder = venv.EnvBuilder(clear=True, with_pip=True)
        builder.create(venv_dir)

    # The installer asks frequently (twice for me) to confirm whether to actually do its job.
    # Simply hitting Enter is the 'yes' option (Ctrl+C is the 'no' option.).
    yeah_yeah_yeah = b"\n"*100
    ap_cmd("ModuleUpdate.py", input=yeah_yeah_yeah, suppress_auto_install=False, repo=repo)

    # We could try to create the default host.yaml now, but I think it's better for the user to see that happen.

    # This module does fancy stuff on import once. Let's get it over with.
    ap_cmd("NetUtils.py", repo=repo)

def do_generate(repo, output_zip_path, output_dir, seed, player_yamls):
    if output_dir:
        if not os.path.isdir(output_dir):
            os.mkdir(output_dir)
        elif len(os.listdir(output_dir)) > 0:
            sys.exit("ERROR: --output-dir is not empty: " + output_dir)
    elif output_zip_path:
        pass # cool ok
    else: assert False

    def fatal_problem(msg):
        print(msg); import pdb; pdb.set_trace()
        sys.exit(msg)

    with tempfile.TemporaryDirectory(prefix="ap_cli.", suffix=".tmp") as tmp_dir:
        players_dir = os.path.join(tmp_dir, "Players")
        os.mkdir(players_dir)

        for i, path in enumerate(player_yamls):
            assert os.path.isfile(path) and path.endswith(".yaml"), "this doesn't look like a player yaml file: " + path
            shutil.copy(path, os.path.join(players_dir, "Player{}.yaml".format(i+1)))

        tmp_output_dir = os.path.join(tmp_dir, "output")

        # Generate
        args = [
            "--player_files_path", players_dir,
            "--outputpath", tmp_output_dir,
        ]
        if seed != -1:
            args.extend(("--seed", int(seed)))
        ap_cmd("Generate.py", *args, repo=repo)

        output_names = os.listdir(tmp_output_dir)
        if not (len(output_names) == 1 and output_names[0].endswith(".zip")):
            fatal_problem("expected a single .zip in the output dir")
        tmp_output_zip_path = os.path.join(tmp_output_dir, output_names[0])

        if output_dir:
            import zipfile
            with zipfile.ZipFile(tmp_output_zip_path) as z:
                z.extractall(output_dir)
        elif output_zip_path:
            shutil.copy(tmp_output_zip_path, output_zip_path)
        else: assert False


def do_factorio(repo, mod_source_path, factorio_root, server_dir):
    if not os.access(os.path.join(factorio_root, "bin/x64/factorio"), os.X_OK):
        sys.exit("ERROR: does not appear to be a factorio root: " + repr(factorio_root))
    # example name: AP-77091154303292394091-P1-josh_0.6.5.zip
    ap_mod_name = re.match(r'^(AP-.*)_\d+\.\d+\.\d+\.zip$', os.path.basename(mod_source_path)).group(1)

    try: os.mkdir(server_dir)
    except FileExistsError: pass

    # Mods
    mods_dir = os.path.join(server_dir, "mods")
    try:
        os.mkdir(mods_dir)
    except FileExistsError:
        shutil.rmtree(mods_dir)
        os.mkdir(mods_dir)
    shutil.copy(mod_source_path, mods_dir + "/")
    mod_list = {"mods": [
        # These are the defaults that ship with space age
        {"name": "base", "enabled": True},
        {"name": "elevated-rails", "enabled": True},
        {"name": "quality", "enabled": True},
        {"name": "space-age", "enabled": True},
    ]}
    # AP is incompatible with space-age
    for mod in mod_list["mods"]:
        if mod["name"] == "space-age":
            mod["enabled"] = False
    # Enable the new mod.
    mod_list["mods"].append({"name": ap_mod_name, "enabled": True})
    with open(os.path.join(mods_dir, "mod-list.json"), "w") as f:
        json.dump(mod_list, f, indent=2)

    # Create a "factorio" executable that wraps invoking it through docker.
    this_repo = os.path.dirname(os.path.abspath(__file__))
    shutil.copy(os.path.join(this_repo, "deps/util/docker-apt-run"), os.path.join(server_dir, "docker-apt-run"))
    factorio_in_docker_path = os.path.join(server_dir, "factorio-in-docker.sh")
    with open(factorio_in_docker_path, "w") as f:
        f.write("".join(line + "\n" for line in [
            "#!/usr/bin/env bash",
            'exec {0}/docker-apt-run -i ca-certificates --mount {1}:{1} -- {1}/bin/x64/factorio --mod-directory {2} "$@"'.format(
                shlex.quote(os.path.abspath(server_dir)),
                shlex.quote(os.path.abspath(factorio_root)),
                shlex.quote(os.path.abspath(mods_dir)),
            ),
        ]))
    chmod_x(factorio_in_docker_path)

    # I believe host.yaml is the only way to configure this executable automatedly.
    # (The yaml file gets formatted and filled out with default values when Launcher.py shuts down.)
    host_j = {"factorio_options": {"executable": os.path.abspath(factorio_in_docker_path)}}
    with open(os.path.join(server_dir, "host.yaml"), "w") as f:
        json.dump(host_j, f)

    ap_cmd("Launcher.py", "Factorio Client", "--", "--nogui", cwd=server_dir, input=None, repo=repo)

def ap_cmd(script, *args, suppress_auto_install=True, input=b'', cwd=None, repo):
    """ cwd defaults to repo """
    if cwd == None:
        cwd = repo

    env = os.environ.copy()
    if suppress_auto_install:
        env["SKIP_REQUIREMENTS_UPDATE"] = "1"
    # We get deprecation warnings for importing pkg_resources. Not our problem, so suppress it.
    env["PYTHONWARNINGS"] = "ignore"

    python_exe = os.path.join(repo, ".venv", "bin", "python")
    cmd = [python_exe, os.path.join(repo, script)]
    cmd.extend(args)
    subprocess.run(cmd, check=True, env=env, input=input, cwd=cwd)

def chmod_x(path):
    # This is like chmod +x, except that umask is preserved by copying the r bit to the x bit.
    st_mode = os.stat(path).st_mode & 0o777
    st_mode |= st_mode >> 2
    os.chmod(path, st_mode)

if __name__ == "__main__":
    main()
