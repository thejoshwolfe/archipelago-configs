#!/usr/bin/env python3

__doc__ = """\
Invokes the Archipelago tools with CLI ergonomics more suitable to stateless automation.

TODO: management for host.yaml values/overrides?
"""

import os, sys, subprocess
import shutil, tempfile

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

    args = parser.parse_args()

    if args.cmd == "update":
        do_update(args.repo)
    elif args.cmd == "init":
        do_init(args.repo)
    elif args.cmd == "generate":
        do_generate(args.repo, args.output_zip, args.output_dir, args.seed, args.player_yaml)
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

def ap_cmd(script, *args, suppress_auto_install=True, input=b'', repo):
    """ cwd is always repo. you gotta give absolute paths as args if you want them to work. """
    python_exe = os.path.join(repo, ".venv", "bin", "python")

    env = os.environ.copy()
    if suppress_auto_install:
        env["SKIP_REQUIREMENTS_UPDATE"] = "1"
    # We get deprecation warnings for importing pkg_resources. Not our problem, so suppress it.
    env["PYTHONWARNINGS"] = "ignore"

    cmd = [python_exe, os.path.join(repo, script)]
    cmd.extend(args)
    subprocess.run(cmd, check=True, env=env, input=input, cwd=repo)

if __name__ == "__main__":
    main()
