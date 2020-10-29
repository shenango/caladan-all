#!/bin/bash

set -e
set -x

# record BASE_DIR
SCRIPT=$(readlink -f "$0")
SCRIPTPATH=$(dirname "$SCRIPT")
echo "BASE_DIR = '${SCRIPTPATH}/'" > base_dir.py

git submodule update --init -f --recursive caladan

if lspci | grep -q 'ConnectX-5'; then
 sed "s/CONFIG_MLX5=.*/CONFIG_MLX5=y/g" -i caladan/build/config
 sed "s/CONFIG_DIRECTPATH=.*/CONFIG_DIRECTPATH=y/g" -i caladan/build/config
elif lspci | grep -q 'ConnectX-4'; then
 sed "s/CONFIG_MLX5=.*/CONFIG_MLX5=y/g" -i caladan/build/config
elif lspci | grep -q 'ConnectX-3'; then
 sed "s/CONFIG_MLX4=.*/CONFIG_MLX4=y/g" -i caladan/build/config
fi

sed "s/CONFIG_SPDK=.*/CONFIG_SPDK=y/g" -i caladan/build/config

pushd caladan
make submodules
make

pushd ksched
make
popd

echo building LOADGEN
pushd apps/synthetic
cargo build --release
popd

popd
