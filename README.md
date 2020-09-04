# caladan-artifact

This repository includes Caladan and several applications that were evaluated in the Caladan paper submitted to OSDI '20.

This repository also includes several scripts to facilitate building the applications and running experiments from the paper.

## Supported Hardware and Software

This code was tested on Ubuntu 18.04 kernel version 5.2.0 on a server with a Mellanox ConnectX-5 40Gb/s NIC and an Intel Optane SSD.

Client machines require either an Intel 82599 based-NIC or a ConnectX-{3,4,5} Mellanox NIC.

## Installing prereqs
First, install any needed packages:
```
sudo apt install build-essential libnuma-dev clang autoconf autotools-dev m4 automake libevent-dev  libpcre++-dev libtool ragel libev-dev moreutils parallel cmake python3 python3-pip libjemalloc-dev libaio-dev libdb5.3++-dev numactl hwloc libmnl-dev libnl-3-dev libnl-route-3-dev uuid-dev
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


## Experiment Scripts
This repository contains a collection of python scripts to execute experiments
from the Caladan paper and to graph the results. 

Each experiment run produces a folder with data collected from the run. To graph
the data, run `python3 graph.py <folder1> <folder2>...`.

The scripts assume that passwordless SSH and passwordless sudo are setup on all the machines in the testbed. 

#### env.py
This file describes the testing environment and should be modified to reflect your setup. We include the default setup for running on our testbed as an example. `MACHINES` should contain information about each of the machines in the testbed, and `CLIENT_SET` should contain the set of machines used to generate load.

Each machine is assumed to have (A) a management interface with its own address (`oob_ip`) that is used for SSH connections and launching experiments and (B) a NIC used for the experiment.


## Running

To run the experiments, follow the above instructions to build and setup your environment. Run `python3 paper_experiments.py` to run all the experiments.

