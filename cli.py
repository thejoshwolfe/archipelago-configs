#!/usr/bin/env python3

__doc__ = """\
Invokes the Archipelago tools with CLI ergonomics more suitable to stateless automation.
"""

import os, sys, subprocess
import shutil, shlex, tempfile, glob
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
    sub_parser.add_argument("--output-dir", required=True, help=
        "Extracts the output .zip file into the given directory. "
        "Created if it doesn't exist; error if exists and not empty.")
    sub_parser.add_argument("--seed", metavar="int", type=int, default=-1, help=
        "Forwarded to Generate.py '--seed'.")
    sub_parser.add_argument("--server", metavar="host:port", help=
        "Goes into any generated archipelag.json manifests. "
        "Enables some clients to connect to the server without prompting.")
    sub_parser.add_argument("player_yaml", nargs="+", help=
        "Path(s) to player .yaml files. "
        "These get copied into a tmp dir and given to Generate.py '--player_files_path'. ")

    sub_parser = subparsers.add_parser("server", help=
        "Calls MultiServer.py. Creates *.apsave next to the given *.archipelago. "
        "Quit with /exit (not Ctrl+C) for clean shutdown.")
    sub_parser.add_argument("--server-dir", required=True, help=
        "The cwd for MultiServer.py. To configure server settings, edit the host.yaml in the server's cwd. "
        "Run 'server' once and /exit to populate the the file with defaults, or manually create one or copy from --repo. "
        "Defaults to --repo.")
    sub_parser.add_argument("--oracle-spoiler")
    sub_parser.add_argument("multidata", help=
        "The AP_*.archipelago from the 'generate' command.")

    sub_parser = subparsers.add_parser("text-client", help=
        "Calls CommonClient.py")
    sub_parser.add_argument("connect_to", metavar="host:port")
    sub_parser.add_argument("slot")

    sub_parser = subparsers.add_parser("generate-template-options", help=
        "Calls Launcher.py 'Generate Template Options' -- --skip_open_folder.")

    sub_parser = subparsers.add_parser("factorio-server", help=
        "How I, a NixOS user, invoke the AP client for Factorio, which runs the Factorio headless server in a docker container. "
        "Requires docker and a downloaded standalone factorio installation. "
        "First, run 'generate' and start the archipelago server, then run this command. "
        "Use the /connect command to connect to the archipelago game, which automatically launches the factorio server locally. "
        "Once the factorio server is running, launch the factorio gui normally (via steam or whatever), and connect to localhost.")
    sub_parser.add_argument("--factorio", metavar="/path/to/standalone/factorio", required=True, help=
        "Download it from https://factorio.com/download . "
        "The dir should contain bin/, data/, etc.")
    sub_parser.add_argument("--mod", metavar="/path/to/AP-*.zip", required=True, help=
        "The mod .zip produced by the 'generate' command. It's got your slot name in the file name.")
    sub_parser.add_argument("--server-dir", required=True, help=
        "The cwd for the factorio server. "
        "The save file called Archipelago.zip goes there, and this script throws stuff in there as well.")
    sub_parser.add_argument("--space-age", action="store_true", help=
        "Experimental")

    sub_parser = subparsers.add_parser("factorio-client", help=
        "Installs the given mod into your client's mods folder ~/.factorio/mods/ and deletes all other AP-* mods.")
    sub_parser.add_argument("--mod", metavar="/path/to/AP-*.zip", required=True, help=
        "The mod .zip produced by the 'generate' command. It's got your slot name in the file name.")

    args = parser.parse_args()

    if args.cmd == "update":
        do_update(args.repo)
    elif args.cmd == "init":
        do_init(args.repo)
    elif args.cmd == "generate":
        do_generate(args.repo, args.output_dir, args.seed, args.server, args.player_yaml)
    elif args.cmd == "server":
        do_server(args.repo, args.server_dir, args.multidata, args.oracle_spoiler)
    elif args.cmd == "text-client":
        do_text_client(args.repo, args.connect_to, args.slot)
    elif args.cmd == "generate-template-options":
        do_generate_template_options(args.repo)
    elif args.cmd == "factorio-server":
        do_factorio_server(args.repo, args.mod, args.factorio, args.server_dir, args.space_age)
    elif args.cmd == "factorio-client":
        do_factorio_client(args.mod)
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
        subprocess.run(["uv", "venv", venv_dir], cwd=repo, check=True)

    # Install everything from world/*/requirements.txt
    # and custom_worlds/{name}.apworld(a zip file)/{name}/requirements.txt
    all_requirements_files = [os.path.join(repo, "requirements.txt")]
    all_requirements_files.extend(glob.glob(os.path.join(repo, "worlds", "*", "requirements.txt")))
    with tempfile.TemporaryDirectory(prefix="ap_cli.", suffix=".tmp") as tmp_dir:
        for zipfile_path in glob.glob(os.path.join(repo, "custom_worlds", "*.apworld")):
            import zipfile
            with zipfile.ZipFile(zipfile_path) as z:
                for inner_item in z.infolist():
                    if inner_item.filename.endswith("/requirements.txt"):
                        assert inner_item.filename == "{}/requirements.txt".format(os.path.splitext(os.path.basename(zipfile_path))[0]), inner_item.filename
                        file = os.path.join(tmp_dir, inner_item.filename.replace("/", "_"))
                        with z.open(inner_item) as in_f:
                            with open(file, "wb") as out_f:
                                out_f.write(in_f.read())
                        all_requirements_files.append(file)

        # I don't make the rules. You have to separate the files based on whether they contain --hash directives.
        hash_enabled_files = []
        hashless_files = []
        for file in all_requirements_files:
            with open(file) as f:
                if "--hash" in f.read():
                    hash_enabled_files.append(file)
                else:
                    hashless_files.append(file)
        for file_list in (hash_enabled_files, hashless_files):
            if len(file_list) == 0: continue
            cmd = ["uv", "pip", "install"]
            for file in file_list:
                cmd.extend(["-r", os.path.abspath(file)])
            subprocess.run(cmd, cwd=repo, check=True)

    # We could try to create the default host.yaml now, but I think it's better for the user to see that happen.

    # This module does fancy stuff on import once. Let's get it over with.
    ap_cmd("NetUtils.py", repo=repo)
    # This also verifies a few of the above dependencies.

def do_generate(repo, output_dir, seed, server, player_yamls):
    if not os.path.isdir(output_dir):
        os.mkdir(output_dir)
    elif len(os.listdir(output_dir)) > 0:
        sys.exit("ERROR: --output-dir is not empty: " + output_dir)

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

        # Extract primary .zip into output dir.
        output_names = os.listdir(tmp_output_dir)
        if not (len(output_names) == 1 and output_names[0].endswith(".zip")):
            fatal_problem("expected a single .zip in the output dir")
        tmp_output_zip_path = os.path.join(tmp_output_dir, output_names[0])
        import zipfile
        with zipfile.ZipFile(tmp_output_zip_path) as z:
            z.extractall(output_dir)

    # Do we have post-generation modifications to do?
    if not server:
        return
    def modify_data(data):
        # If this throws an exception, then full crashing seems appropriate.
        j = json.loads(data)
        j["server"] = server
        return json.dumps(j)

    # Perform post-generation modificiations.
    for file_name in os.listdir(output_dir):
        file_path = os.path.join(output_dir, file_name)
        changed_anything = False
        # Several types of files output by archipelago are in the .zip format and contain a top-level manifest.
        # The file names and extensions are not predicatable, so just try reading everything as a ZIP.
        try:
            with zipfile.ZipFile(file_path) as input_z:
                with zipfile.ZipFile(file_path + ".tmp", "w") as output_z:
                    for info in input_z.infolist():
                        data = input_z.read(info)
                        if info.filename == "archipelago.json":
                            data = modify_data(data)
                            changed_anything = True
                        # Note: even though 'str' is in this name, it operates on bytes. (Holdover from Python 2 I suppose.)
                        output_z.writestr(info, data)
            if changed_anything:
                os.rename(file_path + ".tmp", file_path)
            else:
                # Never mind.
                os.remove(file_path + ".tmp")
        except zipfile.BadZipFile:
            continue

def do_server(repo, server_dir, multidata_path, oracle_spoiler):
    # Do this check now before trusting the AP code with it:
    if not os.path.isfile(multidata_path): raise FileNotFoundError(multidata_path)
    try: os.mkdir(server_dir)
    except FileExistsError: pass

    host_yaml_path = os.path.join(server_dir, "host.yaml")
    if not os.path.isfile(host_yaml_path):
        # The file must exist for settings.py to recognize it.
        # Create an empty yaml document (with the correct top level type).
        with open(host_yaml_path, "w") as f:
            f.write("{}\n")

    args = []
    if oracle_spoiler:
        args.extend(["--oracle-spoiler", os.path.abspath(oracle_spoiler)])
    args.append(os.path.abspath(multidata_path))
    ap_cmd("MultiServer.py", *args, cwd=server_dir, input=None, repo=repo, os_exec=True)


def do_text_client(repo, connect_to, slot_name):
    args = ["--nogui", "--connect", connect_to, "--name", slot_name]
    ap_cmd("CommonClient.py", *args, input=None, repo=repo, os_exec=True)

def do_generate_template_options(repo):
    ap_cmd("Launcher.py", "Generate Template Options", "--", "--skip_open_folder", repo=repo, input=None)

def do_factorio_server(repo, mod_source_path, factorio_root, server_dir, space_age_enabled):
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
            mod["enabled"] = space_age_enabled
        elif mod["name"] in ("elevated-rails", "quality"):
            # These mods do work, sorta, but they're excluded from the randomization experience.
            # Not necessary. Turn them off.
            mod["enabled"] = space_age_enabled
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
    host_yaml_path = os.path.join(server_dir, "host.yaml")
    factorio_in_docker_abs_path = os.path.abspath(factorio_in_docker_path)
    try:
        with open(host_yaml_path) as f:
            existing_contents = f.read()
        if "\n  executable: {}\n".format(json.dumps(factorio_in_docker_abs_path)) in existing_contents:
            # Despite the quotes being optional in yaml (sometimes), settings.py formats strings with quotes unconditionally.
            pass
        else:
            # Don't clobber the other settings.
            sys.exit(
                "ERROR: host.yaml already exists but isn't configured correctly. Please add this configuration to factorio_options:\n"
                "  executable: " + json.dumps(factorio_in_docker_abs_path)
            )
    except FileNotFoundError:
        # The yaml file gets formatted and filled out with default values when Launcher.py shuts down.
        host_j = {"factorio_options": {
            "executable": factorio_in_docker_abs_path,
            # Don't show checks that don't involve us.
            "filter_item_sends": True,
        }}
        with open(host_yaml_path, "w") as f:
            json.dump(host_j, f)

    client_name = "Factorio: Space Age Client" if space_age_enabled else "Factorio Client"
    ap_cmd("Launcher.py", client_name, "--", "--nogui", cwd=server_dir, input=None, repo=repo, os_exec=True)

def do_factorio_client(mod_source_path):
    mods_dir = os.path.expanduser("~/.factorio/mods")
    for name in os.listdir(mods_dir):
        if name.startswith("AP-") and name.endswith(".zip"):
            path = os.path.join(mods_dir, name)
            print("INFO: deleting old AP mod: " + path)
            os.remove(path)

    shutil.copy(mod_source_path, mods_dir + "/")

def ap_cmd(script, *args, suppress_auto_install=True, input=b'', cwd=None, os_exec=False, repo):
    """ cwd defaults to repo """
    if cwd == None:
        cwd = repo
    repo = os.path.abspath(repo)

    assert not (os_exec and input != None), "can't exec with piped stdin"

    env = os.environ.copy()
    if suppress_auto_install:
        env["SKIP_REQUIREMENTS_UPDATE"] = "1"
    # We get deprecation warnings for importing pkg_resources. Not our problem, so suppress it.
    env["PYTHONWARNINGS"] = "ignore"

    python_exe = os.path.join(repo, ".venv", "bin", "python")
    cmd = [python_exe, os.path.join(repo, script)]
    cmd.extend(args)

    if os_exec:
        os.chdir(cwd)
        os.execvpe(cmd[0], cmd, env)
        assert False, "unreachable"
    else:
        subprocess.run(cmd, check=True, env=env, input=input, cwd=cwd)

def chmod_x(path):
    # This is like chmod +x, except that umask is preserved by copying the r bit to the x bit.
    st_mode = os.stat(path).st_mode & 0o777
    st_mode |= st_mode >> 2
    os.chmod(path, st_mode)

if __name__ == "__main__":
    main()
