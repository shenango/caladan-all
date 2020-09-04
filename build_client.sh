#!/bin/bash

set -e
set -x

# record BASE_DIR
SCRIPT=$(readlink -f "$0")
SCRIPTPATH=$(dirname "$SCRIPT")
echo "BASE_DIR = '${SCRIPTPATH}/'" > base_dir.py

git submodule update --init -f --recursive shenango

if lspci | grep -q 'ConnectX-3'; then
  sed "s/CONFIG_MLX4=.*/CONFIG_MLX4=y/g" -i shenango/build/config
elif lspci | grep -q 'ConnectX-5'; then
  for config in MLX5 DIRECTPATH; do
    sed "s/CONFIG_${config}=.*/CONFIG_${config}=y/g" -i shenango/build/config
  done
fi

pushd shenango
build/init_submodules.sh
popd

pushd shenango/ksched
make
popd

echo building LOADGEN
pushd shenango/apps/synthetic
cargo build --release
popd
