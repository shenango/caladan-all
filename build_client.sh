#!/bin/bash

set -e
set -x

# record BASE_DIR
SCRIPT=$(readlink -f "$0")
SCRIPTPATH=$(dirname "$SCRIPT")
echo "BASE_DIR = '${SCRIPTPATH}/'" > base_dir.py

CORES=`getconf _NPROCESSORS_ONLN`

git submodule update --init -f --recursive shenango

if lspci | grep -q 'ConnectX-3'; then
  sed "s/CONFIG_MLX4=.*/CONFIG_MLX4=y/g" -i shenango/build/config
elif lspci | grep -q 'ConnectX-[4,5]'; then
  for config in MLX5 DIRECTPATH; do
    sed "s/CONFIG_${config}=.*/CONFIG_${config}=y/g" -i shenango/build/config
  done
fi

echo building DPDK
pushd shenango
patch -p 1 -d dpdk/ < build/ixgbe_19_11.patch
if lspci | grep -q 'ConnectX-[4,5]'; then
  patch -p 1 -d dpdk/ < build/mlx5_19_11.patch
elif lspci | grep -q 'ConnectX-3'; then
  patch -p 1 -d dpdk/ < build/mlx4_19_11.patch
fi
make -C dpdk/ config T=x86_64-native-linuxapp-gcc
make -C dpdk/ -j $CORES

if lspci | grep -q 'ConnectX-5'; then
echo building RDMA-CORE
pushd rdma-core
git apply ../build/rdma-core.patch
EXTRA_CMAKE_FLAGS=-DENABLE_STATIC=1 MAKEFLAGS=-j$CORES ./build.sh
popd
fi

make

pushd ksched
make
popd

echo building LOADGEN
pushd apps/synthetic
cargo build --release
popd

popd
