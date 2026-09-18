from .services.release import prepare_release


def main() -> None:
    release = prepare_release()
    print(f"Release ready: {release.ready}")
    print(f"Open alerts: {len(release.open_alerts)}")
    print(f"Next action: {release.next_action}")


if __name__ == "__main__":
    main()
