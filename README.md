# caladan-artifact

This repository includes Caladan and several applications that were evaluated in the Caladan paper submitted to OSDI '20.

This repository also includes several scripts to facilitate building the applications and running experiments from the paper.

## Installing prereqs
```
sudo apt install build-essential libnuma-dev clang autoconf autotools-dev m4 automake libevent-dev  libpcre++-dev libtool ragel libev-dev moreutils parallel cmake python3 python3-pip libjemalloc-dev libaio-dev libdb5.3++-dev numactl hwloc
```

Install rust, and use the nightly toolchain. See http://rust-lang.org/ for details.
```
curl https://sh.rustup.rs -sSf | sh
rustup default nightly
```

## Compiling

On the server machine, clone this repository in your home directory and build
everything:
```
cd caladan-artifact
./build_all.sh
```

On each client machine, clone this repository in your home directory and build
using:
```
cd caladan-artifact
./build_client.sh
```

The experiment scripts assume that binaries are located at the same absolute
paths on client and server machines, so please use the same directory names.


<!-- For instructions on building ZygOS or Memcached for ZygOS, please see
[their repositories](https://github.com/ix-project). After building
ZygOS, the spin server can be built with:
```
make -C ./bench/servers spin-ix
```
We built and ran ZygOS on Ubuntu 16.04; we built and ran everything
else on Ubuntu 18.04.
 -->

## Running

To run the experiments, first run the installation instructions above
on your server. On your clients, clone the Shenango repo in your home
directory and build it (the experiments will use the iokernel built
there). Next, on the server, modify `experiment.py` so that the IPs,
MACs, PCIe address, and interface name match those in your
deployment. Also enable the experiments that you would like to run in
`paper_experiments` in `experiment.py`. Then run the main experiments:
```
python experiment.py
```

To run the threading benchmarks (Table 2), follow the instructions in
shenango/apps/bench (for Shenango) and bench/threading (for the other
systems). To run the latency experiment (Figure 6), follow the
instructions in shenango/apps/dpdk_netperf for both building and
running.

## Analyzing
To process the results for the load shift experiment:
```
python loadshift_process.py <results_directory>
```
To process the results for all other experiments:
```
python summary.py <results_directory>
```

To reproduce the figures in the paper, install R and the packages
ggplot2, plyr, and cowplot (e.g., with `install.packages()` in the R
prompt).  Then run the R scripts in the scripts directory. Each script
includes a description of its arguments.
