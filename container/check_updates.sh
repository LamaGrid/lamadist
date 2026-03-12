#!/bin/bash

set -o errexit
set -o nounset
set -o pipefail

_updates_available=false

if uv pip list --system --editable --outdated --strict --format=freeze 2>/dev/null | grep .; then
	echo "Python updates available!"
	_updates_available=true
else
	echo "Python packages are up to date!"
fi

apt-get update >/dev/null
if apt list --upgradable 2>/dev/null | awk 'NR>2 {print $1}' | grep .; then
	echo "APT updates available!"
	_updates_available=true
else
	echo "APT packages are up to date!"
fi

[ "$_updates_available" = true ] && exit 5
exit 0
