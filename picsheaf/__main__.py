"""Entrypoint: `python3 -m picsheaf`."""
import sys

from picsheaf.app import PicsheafApp


def main():
    app = PicsheafApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
