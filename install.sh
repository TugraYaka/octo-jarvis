#!/bin/sh
# Installs JARVIS: downloads the latest release for this machine and adds the 'jarvis' command.
#   curl -fsSL https://raw.githubusercontent.com/TugraYaka/octo-jarvis/main/install.sh | sh
set -eu

REPO="TugraYaka/octo-jarvis"

case "$(uname -s)" in
  Darwin) os=macos ;;
  Linux) os=linux ;;
  *) echo "Unsupported system: $(uname -s). On Windows use install.ps1." >&2; exit 1 ;;
esac
case "$(uname -m)" in
  arm64|aarch64) arch=arm64 ;;
  x86_64|amd64) arch=x64 ;;
  *) echo "Unsupported CPU: $(uname -m)" >&2; exit 1 ;;
esac
if [ "$os" = macos ] && [ "$arch" = x64 ]; then
  echo "Intel Macs have no prebuilt package yet. Install from source instead (see the README)." >&2
  exit 1
fi

if [ -n "${JARVIS_HOME:-}" ]; then
  data="$JARVIS_HOME"
elif [ "$os" = macos ]; then
  data="$HOME/Library/Application Support/JARVIS"
else
  data="${XDG_DATA_HOME:-$HOME/.local/share}/jarvis"
fi

name="jarvis-$os-$arch.tar.gz"
if [ -n "${JARVIS_BASE_URL:-}" ]; then
  base="$JARVIS_BASE_URL"
elif [ -n "${JARVIS_VERSION:-}" ]; then
  base="https://github.com/$REPO/releases/download/$JARVIS_VERSION"
else
  base="https://github.com/$REPO/releases/latest/download"
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "Downloading $name ..."
curl -fL --progress-bar -o "$tmp/$name" "$base/$name"
curl -fsSL -o "$tmp/$name.sha256" "$base/$name.sha256"

expected="$(cut -d' ' -f1 "$tmp/$name.sha256")"
if command -v sha256sum >/dev/null 2>&1; then
  actual="$(sha256sum "$tmp/$name" | cut -d' ' -f1)"
else
  actual="$(shasum -a 256 "$tmp/$name" | cut -d' ' -f1)"
fi
if [ "$expected" != "$actual" ]; then
  echo "Checksum mismatch, aborting." >&2
  exit 1
fi

mkdir -p "$data"
rm -rf "$data/app.new"
mkdir -p "$data/app.new"
tar -xzf "$tmp/$name" -C "$data/app.new" --strip-components=1
rm -rf "$data/app"
mv "$data/app.new" "$data/app"

if (: < /dev/tty) 2>/dev/null; then
  "$data/app/jarvis" install < /dev/tty
else
  "$data/app/jarvis" install
fi

echo
echo "JARVIS installed. Run 'jarvis setup' for the guided setup, or just 'jarvis'."
