#!/bin/bash

set -e
set -x

git submodule update --init -f --recursive

. build_client.sh

echo building SNAPPY
pushd caladan/apps/storage_service
./snappy.sh
popd

echo building CALADAN
for dir in caladan caladan/shim caladan/bindings/cc caladan/apps/storage_service caladan/apps/netbench; do
	make -C $dir
done


export SHENANGODIR=$SCRIPTPATH/caladan

echo building SILO
pushd  silo
./silo.sh
make
popd

echo building MEMCACHED
pushd memcached
./autogen.sh
./configure --with-shenango=$SCRIPTPATH/caladan
make
popd
pushd memcached-linux
./autogen.sh
./configure
make
popd

echo building BOEHMGC
pushd gc
./autogen.sh
./configure --prefix=$SCRIPTPATH/gc/build --enable-static --enable-large-config --enable-handle-fork=no --enable-dlopen=no --disable-java-finalization --enable-threads=shenango --enable-shared=no --with-shenango=$SCRIPTPATH/caladan
make install
popd

echo building PARSEC
for p in x264 swaptions streamcluster; do
	parsec/bin/parsecmgmt -a build -p $p -c gcc-shenango
done
export GCDIR=$SCRIPTPATH/gc/build/
parsec/bin/parsecmgmt -a build -p swaptions -c gcc-shenango-gc
