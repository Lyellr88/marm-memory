from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable


def add_docker_commands(
    subparsers: argparse._SubParsersAction,
    add_run_arguments: Callable[[argparse.ArgumentParser], None],
) -> None:
    """Register Docker commands while keeping the product parser concise."""
    docker = subparsers.add_parser("docker", help="Manage official MARM Docker images")
    docker_sub = docker.add_subparsers(dest="docker_command", required=True)
    docker_status = docker_sub.add_parser(
        "status", help="Inspect a managed MARM container"
    )
    docker_status.add_argument("--name", default="marm-mcp-server")
    docker_pull = docker_sub.add_parser(
        "pull", help="Pull an official image without starting it"
    )
    docker_pull.add_argument("--tag", default="latest")
    docker_run = docker_sub.add_parser(
        "run", help="Create a managed MARM HTTP container"
    )
    add_run_arguments(docker_run)
    docker_run.add_argument("--dry-run", action="store_true")
    docker_command = docker_sub.add_parser(
        "command", help="Print the exact Docker HTTP command"
    )
    add_run_arguments(docker_command)
    docker_compose = docker_sub.add_parser(
        "compose", help="Preview or write a safe Docker Compose configuration"
    )
    add_run_arguments(docker_compose)
    docker_compose.add_argument(
        "--output", type=Path, default=Path.home() / ".marm" / "marm-compose.yaml"
    )
    docker_compose.add_argument(
        "--yes",
        action="store_true",
        help="Write the Compose file instead of previewing it",
    )
    docker_stdio = docker_sub.add_parser(
        "stdio-command", help="Print a Docker STDIO client command"
    )
    docker_stdio.add_argument("--tag", default="latest")
    docker_stdio.add_argument("--data-dir", type=Path, default=Path.home() / ".marm")
    docker_stdio.add_argument("--client")
    docker_logs = docker_sub.add_parser("logs", help="Read managed container logs")
    docker_logs.add_argument("--name", default="marm-mcp-server")
    docker_logs.add_argument("--follow", action="store_true")
    docker_stop = docker_sub.add_parser("stop", help="Stop a managed MARM container")
    docker_stop.add_argument("--name", default="marm-mcp-server")
    docker_sub.add_parser(
        "upgrade", help="Explain the current safe Docker upgrade path"
    )
    docker_maintenance = docker_sub.add_parser("maintenance")
    docker_maintenance_sub = docker_maintenance.add_subparsers(
        dest="docker_maintenance_command", required=True
    )
    docker_embeddings = docker_maintenance_sub.add_parser("embeddings")
    docker_embeddings_sub = docker_embeddings.add_subparsers(
        dest="docker_embeddings_command", required=True
    )
    docker_migrate = docker_embeddings_sub.add_parser("migrate")
    docker_migrate.add_argument("--tag", default="latest")
    docker_migrate.add_argument("--data-dir", type=Path, default=Path.home() / ".marm")
    docker_migrate.add_argument("--name", default="marm-mcp-server")


def dispatch_docker(args: argparse.Namespace, *, print_payload: Callable) -> int:
    """Run one Docker command using the shared safe planner/executor."""
    from . import docker_commands

    if args.docker_command == "status":
        print_payload(docker_commands.docker_status(args.name))
        return 0
    if args.docker_command == "pull":
        print(f"Pulled {docker_commands.pull_image(args.tag)}")
        return 0
    if args.docker_command in {"run", "command", "compose"}:
        options = docker_commands.DockerRunOptions(
            profile=args.profile,
            port=args.port,
            data_dir=args.data_dir,
            name=args.name,
            tag=args.tag,
            repositories=tuple(args.repo),
            pull=args.pull,
            expose_network=args.expose_network,
            rate_limit_rpm=args.rate_limit_rpm,
            env_file=args.env_file,
            memory=args.memory,
            cpus=args.cpus,
        )
        if args.docker_command == "compose":
            if args.yes:
                payload = docker_commands.write_compose_file(options, args.output)
                print(f"Wrote Compose configuration: {payload['path']}")
                print(docker_commands.shell_command(payload["command"]))
            else:
                payload = docker_commands.compose_document(options)
                print(json.dumps(payload["document"], indent=2))
                print(
                    "Preview only. Re-run with --yes to write "
                    f"{args.output.expanduser().resolve()}."
                )
            return 0
        if args.docker_command == "command" or getattr(args, "dry_run", False):
            plan = docker_commands.build_run_plan(options, require_data_dir=False)
            print(docker_commands.shell_command(plan["arguments"]))
            print(f"Data: {plan['data_dir']}")
            print(f"Key file: {plan['env_file']}")
            for mapping in plan["repository_mappings"]:
                print(f"Repository: {mapping}")
            if options.expose_network:
                print("Network exposure requested: configure a firewall and TLS proxy.")
            return 0
        plan = docker_commands.run_container(options)
        print(f"MARM Docker container ready: http://127.0.0.1:{args.port}/mcp")
        if options.expose_network:
            print("Network exposure is active: configure a firewall and TLS proxy.")
        for mapping in plan["repository_mappings"]:
            print(f"Repository available to index: {mapping}")
        return 0
    if args.docker_command == "stdio-command":
        plan = docker_commands.stdio_command(tag=args.tag, data_dir=args.data_dir)
        print(docker_commands.shell_command(plan["arguments"]))
        if args.client:
            print(
                f"Configure {args.client} with the command above as its STDIO transport."
            )
        return 0
    if args.docker_command == "logs":
        return docker_commands.docker_logs(args.name, follow=args.follow)
    if args.docker_command == "stop":
        print(
            "MARM Docker container stopped."
            if docker_commands.stop_container(args.name)
            else "MARM Docker container is not present."
        )
        return 0
    if args.docker_command == "upgrade":
        raise RuntimeError(
            "Docker upgrade is not automated yet because MARM will not recreate "
            "a container without preserving and confirming its exact configuration. "
            "Run `marm-memory docker pull`, inspect the container, then replace it "
            "manually when ready."
        )
    if (
        args.docker_command == "maintenance"
        and args.docker_embeddings_command == "migrate"
    ):
        exit_code = docker_commands.migrate_embeddings(
            tag=args.tag, data_dir=args.data_dir, name=args.name
        )
        if exit_code == 0:
            print("Docker embedding migration complete.")
        else:
            print(
                f"Docker embedding migration exited with code {exit_code}.",
                file=sys.stderr,
            )
        return exit_code
    return 2
