#!/usr/bin/env bash
set -euo pipefail

#docker pull ghcr.io/vitalii-kaplan/knime2py:0.1.15
docker pull ghcr.io/vitalii-kaplan/knime2py:main

docker run --rm ghcr.io/vitalii-kaplan/knime2py:main --version

docker run --rm \
  -v "$PWD/tests/data/discounts.zip:/in/discounts.zip:ro" \
  -v "$PWD/tests/out:/out:rw" \
  ghcr.io/vitalii-kaplan/knime2py:main \
  --in-zip /in/discounts.zip --out /out